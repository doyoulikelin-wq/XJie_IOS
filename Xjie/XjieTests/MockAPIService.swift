import Foundation
@testable import Xjie

/// 测试用 Mock API 服务
/// 使用方法：设置 handler 闭包控制返回值/抛错，或使用默认的 result/error
actor MockAPIService: APIServiceProtocol {
    // 记录所有请求路径，用于断言
    var requestedPaths: [String] = []

    // 通用返回值 — 设置后所有 get/post/patch/delete 返回此 JSON
    var resultJSON: Data?
    // 通用错误 — 设置后所有请求抛此错误
    var errorToThrow: Error?

    // 按路径返回不同数据
    var responseMap: [String: Data] = [:]

    func setResult<T: Encodable>(_ value: T) throws {
        resultJSON = try JSONEncoder().encode(value)
    }

    func setError(_ error: Error) {
        errorToThrow = error
    }

    func setResponse<T: Encodable>(for path: String, value: T) throws {
        responseMap[path] = try JSONEncoder().encode(value)
    }

    private func resolve<T: Decodable>(_ path: String) throws -> T {
        requestedPaths.append(path)
        if let err = errorToThrow { throw err }
        let data = responseMap[path] ?? resultJSON
        guard let data else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    func get<T: Decodable>(_ path: String, timeout: TimeInterval?) async throws -> T {
        try resolve(path)
    }

    func post<T: Decodable>(_ path: String, body: Encodable?, timeout: TimeInterval?) async throws -> T {
        try resolve(path)
    }

    func patch<T: Decodable>(_ path: String, body: Encodable?) async throws -> T {
        try resolve(path)
    }

    func put<T: Decodable>(_ path: String, body: Encodable?) async throws -> T {
        try resolve(path)
    }

    func delete<T: Decodable>(_ path: String) async throws -> T {
        try resolve(path)
    }

    func postVoid(_ path: String, body: Encodable?) async throws {
        requestedPaths.append(path)
        if let err = errorToThrow { throw err }
    }

    func patchVoid(_ path: String, body: Encodable?) async throws {
        requestedPaths.append(path)
        if let err = errorToThrow { throw err }
    }

    func putVoid(_ path: String, body: Encodable?) async throws {
        requestedPaths.append(path)
        if let err = errorToThrow { throw err }
    }

    func deleteVoid(_ path: String) async throws {
        requestedPaths.append(path)
        if let err = errorToThrow { throw err }
    }

    func uploadFile(_ path: String, fileData: Data, fileName: String, mimeType: String, formData: [String: String]) async throws -> Data {
        requestedPaths.append(path)
        if let err = errorToThrow { throw err }
        return resultJSON ?? Data()
    }
}
