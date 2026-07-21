"""Deterministic quality and completeness checks for report assets.

The detector deliberately runs before OCR.  It never treats a successful file
decode as proof that a page is readable, and it never silently truncates PDFs.
All thresholds are versioned so production evidence can be tied to the exact
decision policy that produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Literal


IMAGE_DETECTOR_ID = "report-image-quality"
IMAGE_DETECTOR_VERSION = "laplacian-tenengrad-v1"
COMPLETENESS_DETECTOR_ID = "report-page-completeness"
COMPLETENESS_DETECTOR_VERSION = "ordered-manifest-v1"

MIN_SHORT_EDGE_PX = 480
BLANK_STDDEV_MAX = 3.0
BLANK_ENTROPY_MAX = 1.2
BLUR_LAPLACIAN_MAX = 55.0
BLUR_TENENGRAD_MAX = 240.0
PDF_MAX_ACCEPTED_PAGES = 100


class ReportAssetQualityError(ValueError):
    """A fail-closed asset error with a stable, non-localized code."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ImageQualityAssessment:
    quality_status: Literal["accepted", "blurry", "blank", "unreadable", "low_resolution"]
    failure_code: str | None
    blur_score: float | None
    width_px: int | None
    height_px: int | None
    metrics: dict[str, float | int | str]
    detector_id: str = IMAGE_DETECTOR_ID
    detector_version: str = IMAGE_DETECTOR_VERSION


@dataclass(frozen=True)
class CompletenessAssessment:
    completeness_status: Literal["complete", "missing_page", "invalid_manifest"]
    expected_page_count: int
    observed_page_count: int
    missing_page_indices: list[int]
    evidence: dict
    failure_code: str | None
    detector_id: str = COMPLETENESS_DETECTOR_ID
    detector_version: str = COMPLETENESS_DETECTOR_VERSION


@dataclass(frozen=True)
class RenderedPDFPage:
    page_index: int
    png_bytes: bytes
    width_px: int
    height_px: int
    extracted_text: str


def _imports():
    try:
        import numpy as np  # type: ignore
        from PIL import Image, ImageOps  # type: ignore
    except Exception as exc:  # pragma: no cover - packaging contract, exercised in deployment
        raise ReportAssetQualityError(
            "quality_component_unavailable",
            "Pillow and NumPy are required for report image quality checks",
        ) from exc
    return np, Image, ImageOps


def assess_image_quality(image_bytes: bytes) -> ImageQualityAssessment:
    """Decode a real image and classify resolution, blankness, and blur.

    Blur requires both a low Laplacian variance and a low Tenengrad response.
    This avoids treating a low-contrast but sharp report as blurry based on one
    fragile signal.  Metrics are calculated over the whole normalized page and
    are persisted by the caller as detector evidence.
    """

    np, Image, ImageOps = _imports()
    try:
        with Image.open(BytesIO(image_bytes)) as source:
            normalized = ImageOps.exif_transpose(source).convert("L")
            width, height = normalized.size
            pixels = np.asarray(normalized, dtype=np.float32)
    except Exception:
        return ImageQualityAssessment(
            quality_status="unreadable",
            failure_code="unreadable_image",
            blur_score=None,
            width_px=None,
            height_px=None,
            metrics={"decode": "failed"},
        )

    if width <= 2 or height <= 2:
        return ImageQualityAssessment(
            quality_status="low_resolution",
            failure_code="low_resolution",
            blur_score=0.0,
            width_px=width,
            height_px=height,
            metrics={"width_px": width, "height_px": height},
        )

    stddev = float(pixels.std())
    histogram = np.bincount(pixels.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    probabilities = histogram[histogram > 0] / histogram.sum()
    entropy = float(-(probabilities * np.log2(probabilities)).sum())

    center = pixels[1:-1, 1:-1]
    laplacian = (
        pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
        - (4.0 * center)
    )
    laplacian_variance = float(laplacian.var())
    grad_x = pixels[1:-1, 2:] - pixels[1:-1, :-2]
    grad_y = pixels[2:, 1:-1] - pixels[:-2, 1:-1]
    tenengrad = float(np.mean((grad_x * grad_x) + (grad_y * grad_y)))
    edge_density = float(np.mean(np.sqrt((grad_x * grad_x) + (grad_y * grad_y)) >= 20.0))
    clipped_fraction = float(np.mean((pixels <= 3.0) | (pixels >= 252.0)))
    metrics: dict[str, float | int | str] = {
        "width_px": width,
        "height_px": height,
        "stddev": round(stddev, 4),
        "entropy": round(entropy, 4),
        "laplacian_variance": round(laplacian_variance, 4),
        "tenengrad": round(tenengrad, 4),
        "edge_density": round(edge_density, 6),
        "clipped_fraction": round(clipped_fraction, 6),
    }

    if min(width, height) < MIN_SHORT_EDGE_PX:
        return ImageQualityAssessment(
            quality_status="low_resolution",
            failure_code="low_resolution",
            blur_score=laplacian_variance,
            width_px=width,
            height_px=height,
            metrics=metrics,
        )
    if stddev <= BLANK_STDDEV_MAX and entropy <= BLANK_ENTROPY_MAX:
        return ImageQualityAssessment(
            quality_status="blank",
            failure_code="blank_page",
            blur_score=laplacian_variance,
            width_px=width,
            height_px=height,
            metrics=metrics,
        )
    if laplacian_variance < BLUR_LAPLACIAN_MAX and tenengrad < BLUR_TENENGRAD_MAX:
        return ImageQualityAssessment(
            quality_status="blurry",
            failure_code="blur",
            blur_score=laplacian_variance,
            width_px=width,
            height_px=height,
            metrics=metrics,
        )
    return ImageQualityAssessment(
        quality_status="accepted",
        failure_code=None,
        blur_score=laplacian_variance,
        width_px=width,
        height_px=height,
        metrics=metrics,
    )


def assess_page_completeness(
    *, expected_page_count: int, observed_page_indices: list[int], basis: str
) -> CompletenessAssessment:
    """Validate an ordered manifest without inventing pages that were not seen."""

    if expected_page_count < 1:
        raise ReportAssetQualityError("invalid_manifest", "expected_page_count must be positive")
    observed = list(observed_page_indices)
    unique = sorted(set(observed))
    invalid = len(unique) != len(observed) or any(index < 1 or index > expected_page_count for index in unique)
    expected = set(range(1, expected_page_count + 1))
    missing = sorted(expected - set(unique))
    evidence = {
        "basis": basis,
        "observed_page_indices": unique,
        "duplicate_indices_present": len(unique) != len(observed),
    }
    if invalid:
        return CompletenessAssessment(
            completeness_status="invalid_manifest",
            expected_page_count=expected_page_count,
            observed_page_count=len(unique),
            missing_page_indices=missing,
            evidence=evidence,
            failure_code="invalid_page_manifest",
        )
    if missing:
        return CompletenessAssessment(
            completeness_status="missing_page",
            expected_page_count=expected_page_count,
            observed_page_count=len(unique),
            missing_page_indices=missing,
            evidence=evidence,
            failure_code="missing_page",
        )
    return CompletenessAssessment(
        completeness_status="complete",
        expected_page_count=expected_page_count,
        observed_page_count=len(unique),
        missing_page_indices=[],
        evidence=evidence,
        failure_code=None,
    )


def render_pdf_pages(
    pdf_bytes: bytes, *, max_pages: int = PDF_MAX_ACCEPTED_PAGES, scale: float = 2.0
) -> list[RenderedPDFPage]:
    """Render every PDF page or fail with an explicit stable reason.

    Returning a prefix of a document is forbidden: it would make a truncated
    report look complete.  Oversized PDFs therefore fail before page rendering.
    """

    try:
        import pypdfium2 as pdfium  # type: ignore
    except Exception as exc:  # pragma: no cover - packaging contract
        raise ReportAssetQualityError(
            "pdf_component_unavailable", "pypdfium2 is required for PDF report processing"
        ) from exc
    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:
        raise ReportAssetQualityError("unreadable_pdf", "PDF could not be opened") from exc
    try:
        page_count = len(document)
        if page_count < 1:
            raise ReportAssetQualityError("empty_pdf", "PDF contains no pages")
        if page_count > max_pages:
            raise ReportAssetQualityError(
                "too_many_pages", f"PDF has {page_count} pages; maximum accepted is {max_pages}"
            )
        rendered: list[RenderedPDFPage] = []
        for offset in range(page_count):
            page = document[offset]
            try:
                text = ""
                try:
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_range() or ""
                    finally:
                        text_page.close()
                except Exception:
                    text = ""
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert("RGB")
                    buffer = BytesIO()
                    image.save(buffer, format="PNG", optimize=True)
                    width, height = image.size
                finally:
                    bitmap.close()
                rendered.append(
                    RenderedPDFPage(
                        page_index=offset + 1,
                        png_bytes=buffer.getvalue(),
                        width_px=width,
                        height_px=height,
                        extracted_text=text,
                    )
                )
            except ReportAssetQualityError:
                raise
            except Exception as exc:
                raise ReportAssetQualityError(
                    "pdf_page_render_failed", f"PDF page {offset + 1} could not be rendered"
                ) from exc
            finally:
                page.close()
        if len(rendered) != page_count:
            raise ReportAssetQualityError("missing_page", "Not every PDF page was rendered")
        return rendered
    finally:
        document.close()
