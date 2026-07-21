import XCTest
@testable import Xjie

/// Utils 工具函数单元测试
final class UtilsTests: XCTestCase {

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
