import XCTest
import SwiftUI
@testable import Xjie

private enum XAgeStyleTestField: Hashable {
    case input
}

/// Utils 工具函数单元测试
final class UtilsTests: XCTestCase {

    // MARK: - XAGE shared styles

    @MainActor
    func testXAgeGlassTextFieldSupportsGenericFocusFields() {
        var text = ""
        let textBinding = Binding(
            get: { text },
            set: { text = $0 }
        )
        let focusState = FocusState<XAgeStyleTestField?>()

        let field = XAgeGlassTextField(
            placeholder: "测试输入",
            text: textBinding,
            field: .input,
            focusedField: focusState.projectedValue
        )

        XCTAssertEqual(field.placeholder, "测试输入")
        XCTAssertEqual(field.field, .input)
    }

    @MainActor
    func testXAgeStyleComponentsPreviewHasStandaloneInitializer() {
        _ = XAgeStyleComponentsPreview()
    }

    @MainActor
    func testXAgeRoundedFieldBackgroundUsesEighteenPointDefaultRadius() {
        let defaultBackground = XAgeRoundedFieldBackground()
        let customBackground = XAgeRoundedFieldBackground(cornerRadius: 24)

        XCTAssertEqual(defaultBackground.cornerRadius, 18)
        XCTAssertEqual(customBackground.cornerRadius, 24)
    }

    // MARK: - formatDate

    func testFormatDateWithISO8601FractionalSeconds() {
        // 2024-01-15T08:30:00.000Z → 某个本地时间
        let result = Utils.formatDate("2024-01-15T08:30:00.000Z")
        XCTAssertFalse(result.isEmpty)
        XCTAssertTrue(result.contains("2024-01-15"), "应包含日期部分")
    }

    func testFormatDateWithISO8601NoFraction() {
        let result = Utils.formatDate("2024-01-15T08:30:00Z")
        XCTAssertFalse(result.isEmpty)
        XCTAssertTrue(result.contains("2024-01-15"))
    }

    func testFormatDateNilReturnsEmpty() {
        XCTAssertEqual(Utils.formatDate(nil), "")
    }

    func testFormatDateEmptyReturnsEmpty() {
        XCTAssertEqual(Utils.formatDate(""), "")
    }

    func testFormatDateInvalidReturnsOriginal() {
        XCTAssertEqual(Utils.formatDate("not-a-date"), "not-a-date")
    }

    // MARK: - formatTime

    func testFormatTimeReturnsHHmm() {
        let result = Utils.formatTime("2024-01-15T14:30:00.000Z")
        XCTAssertFalse(result.isEmpty)
        // 结果取决于时区，但格式应为 HH:mm
        XCTAssertTrue(result.count <= 5, "HH:mm 最长 5 字符")
    }

    func testFormatTimeNilReturnsEmpty() {
        XCTAssertEqual(Utils.formatTime(nil), "")
    }

    // MARK: - toFixed

    func testToFixedDefault1Decimal() {
        XCTAssertEqual(Utils.toFixed(3.14159), "3.1")
    }

    func testToFixedCustomDecimals() {
        XCTAssertEqual(Utils.toFixed(3.14159, n: 2), "3.14")
        XCTAssertEqual(Utils.toFixed(3.14159, n: 0), "3")
    }

    func testToFixedNilReturnsDash() {
        XCTAssertEqual(Utils.toFixed(nil), "--")
    }

    func testToFixedNaNReturnsDash() {
        XCTAssertEqual(Utils.toFixed(Double.nan), "--")
    }

    func testToFixedZero() {
        XCTAssertEqual(Utils.toFixed(0.0), "0.0")
    }

    // MARK: - glucoseColor

    func testGlucoseColorLow() {
        XCTAssertEqual(Utils.glucoseColor(50), .low)
        XCTAssertEqual(Utils.glucoseColor(69.9), .low)
    }

    func testGlucoseColorNormal() {
        XCTAssertEqual(Utils.glucoseColor(70), .normal)
        XCTAssertEqual(Utils.glucoseColor(120), .normal)
        XCTAssertEqual(Utils.glucoseColor(180), .normal)
    }

    func testGlucoseColorHigh() {
        XCTAssertEqual(Utils.glucoseColor(180.1), .high)
        XCTAssertEqual(Utils.glucoseColor(300), .high)
    }

    func testGlucoseColorNilReturnsNormal() {
        XCTAssertEqual(Utils.glucoseColor(nil), .normal)
    }

    // MARK: - maskedPhone

    func testMaskedPhoneShowsOnlyRequiredDigits() {
        XCTAssertEqual(Utils.maskedPhone("13800131234"), "138****1234")
    }

    func testMaskedPhoneRejectsMissingOrMalformedValues() {
        XCTAssertEqual(Utils.maskedPhone(nil), "暂未获取")
        XCTAssertEqual(Utils.maskedPhone(""), "暂未获取")
        XCTAssertEqual(Utils.maskedPhone("1380013123"), "暂未获取")
        XCTAssertEqual(Utils.maskedPhone("13800A31234"), "暂未获取")
    }

    // MARK: - MedicationQuickInput

    func testMedicationQuickInputReplacesDoseAndFrequency() {
        XCTAssertEqual(
            MedicationQuickInput.applying("每日3次", to: "每日1次", behavior: .replace),
            "每日3次"
        )
    }

    func testMedicationQuickInstructionUsesPhraseForEmptyOrWhitespaceContent() {
        XCTAssertEqual(
            MedicationQuickInput.applying("饭后服用", to: "", behavior: .appendInstruction),
            "饭后服用"
        )
        XCTAssertEqual(
            MedicationQuickInput.applying("随餐服用", to: "   ", behavior: .appendInstruction),
            "随餐服用"
        )
    }

    func testMedicationQuickInstructionAppendsWithChineseComma() {
        XCTAssertEqual(
            MedicationQuickInput.applying("睡前服用", to: "整片吞服", behavior: .appendInstruction),
            "整片吞服，睡前服用"
        )
    }

    func testMedicationQuickInputExposesApprovedOptions() {
        XCTAssertEqual(MedicationQuickInput.dosageOptions, ["半片", "1片", "2片", "5mg", "10mg"])
        XCTAssertEqual(MedicationQuickInput.frequencyOptions, ["每日1次", "每日2次", "每日3次", "睡前1次", "按需服用"])
        XCTAssertEqual(MedicationQuickInput.instructionOptions, ["饭后服用", "随餐服用", "空腹服用", "睡前服用", "整片吞服"])
    }

    // MARK: - URLBuilder

    func testURLBuilderEmptyQueryItems() {
        XCTAssertEqual(URLBuilder.path("/api/test", queryItems: []), "/api/test")
    }

    func testURLBuilderWithQueryItems() {
        let result = URLBuilder.path("/api/glucose", queryItems: [
            URLQueryItem(name: "from", value: "2024-01-01"),
            URLQueryItem(name: "limit", value: "100"),
        ])
        XCTAssertTrue(result.hasPrefix("/api/glucose?"))
        XCTAssertTrue(result.contains("from=2024-01-01"))
        XCTAssertTrue(result.contains("limit=100"))
    }

    func testURLBuilderEncodesSpecialCharacters() {
        let result = URLBuilder.path("/api/test", queryItems: [
            URLQueryItem(name: "q", value: "hello world"),
        ])
        // 空格应被编码
        XCTAssertFalse(result.contains(" "))
        XCTAssertTrue(result.contains("q=hello"))
    }

    // MARK: - MIMETypeHelper

    func testMIMETypeKnownExtensions() {
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "photo.jpg"), "image/jpeg")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "photo.jpeg"), "image/jpeg")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "image.png"), "image/png")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "scan.heic"), "image/heic")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "scan.heif"), "image/heif")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "image.webp"), "image/webp")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "archive.tiff"), "image/tiff")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "data.csv"), "text/csv")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "report.pdf"), "application/pdf")
    }

    func testMIMETypeUnknownExtension() {
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "file.xyz"), "application/octet-stream")
    }

    func testMIMETypeCaseInsensitive() {
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "PHOTO.JPG"), "image/jpeg")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "SCAN.HEIC"), "image/heic")
        XCTAssertEqual(MIMETypeHelper.mimeType(forFileName: "data.CSV"), "text/csv")
    }
}
