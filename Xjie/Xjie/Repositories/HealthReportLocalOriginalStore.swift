import CryptoKit
import Foundation

/// 本地保存的一页报告原件。`data` 是用户选择文件的逐字节副本，未经过压缩或转码。
struct HealthReportLocalOriginalAsset: Equatable, Identifiable, Sendable {
    /// 报告内从 1 开始的页序。
    let assetIndex: Int
    /// 用户选择时的文件名，仅用于界面展示。
    let fileName: String
    /// 根据扩展名推断的 MIME 类型。
    let mimeType: String
    /// 持久化时记录并在读取时复核的字节数。
    let byteSize: Int
    /// 持久化时记录并在读取时复核的 SHA-256。
    let sha256: String
    /// 通过完整性校验后的原始字节。
    let data: Data

    var id: Int { assetIndex }
}

/// 报告原件的轻量索引。这里只包含 manifest 与文件属性，不会把报告正文读入内存。
struct HealthReportLocalOriginalMetadata: Equatable, Identifiable, Sendable {
    /// 报告内从 1 开始的页序。
    let assetIndex: Int
    /// 用户选择时的安全展示文件名。
    let fileName: String
    /// 上传时记录的 MIME 类型。
    let mimeType: String
    /// 本机文件属性与 manifest 均确认的字节数。
    let byteSize: Int
    /// 上传落盘时记录的摘要；实际打开单页时才重新读取正文并复核。
    let sha256: String

    var id: Int { assetIndex }
}

/// 本机原件绑定证明，供客户端与服务端确认同一份报告原件契约。
struct HealthReportLocalOriginalBindingProof: Equatable, Sendable {
    let contractVersion: Int
    let clientRequestID: String
    let assetCount: Int
    let aggregateSHA256: String
}

/// 绑定事务的可控中断点，仅用于确定性验证崩溃恢复；生产默认不注入中断。
enum HealthReportLocalOriginalBindingCheckpoint: String, CaseIterable, Sendable {
    case journalPersisted
    case manifestPersisted
    case bindingPersisted
}

enum HealthReportLocalOriginalStoreError: LocalizedError, Equatable {
    case invalidIdentity
    case invalidAsset(index: Int)
    case reportNotFound
    case corruptManifest
    case integrityMismatch(index: Int)
    case writeFailed

    var errorDescription: String? {
        switch self {
        case .invalidIdentity:
            return "当前报告的账号或用户信息无效，请重新登录后再试。"
        case .invalidAsset:
            return "报告原件为空或页序无效，请重新选择文件。"
        case .reportNotFound:
            return "这份报告的本地原件不存在，可尝试从服务器重新加载。"
        case .corruptManifest:
            return "报告原件索引已损坏，请重新上传原文件。"
        case .integrityMismatch:
            return "报告原件完整性校验失败，请重新上传原文件。"
        case .writeFailed:
            return "报告原件未能安全保存到本机，本次不会上传，请检查存储空间后重试。"
        }
    }
}

/// 上传链路只依赖这组最小接口，测试可注入失败实现，证明本地保存失败时不会发起网络请求。
protocol HealthReportLocalOriginalStoreProtocol: Sendable {
    /// 原子保存整份上传输入。
    /// - Parameters:
    ///   - inputs: 按用户选择顺序排列的原始文件。
    ///   - clientRequestID: 本次上传的稳定客户端请求 ID。
    ///   - accountScope: 当前账号的不可逆作用域。
    ///   - subjectUserID: 当前报告所属的数字用户 ID。
    func persistUpload(
        inputs: [HealthReportUploadAssetInput],
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) async throws

    /// 在补页或替换页发网前，先原子更新对应本地原件。
    func persistReplacement(
        input: HealthReportUploadAssetInput,
        assetIndex: Int,
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) async throws

    /// seal 返回工作流后写入永久映射，让新页面和 App 重启后仍能按工作流找到原件。
    func bindWorkflow(
        workflowID: Int,
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) async throws

    /// 读取并逐页复核字节数和 SHA-256；账号或主体不匹配时只返回“未找到”。
    func loadAssets(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) async throws -> [HealthReportLocalOriginalAsset]

    /// 只读取 manifest 和逐文件属性，不加载任何报告正文。
    func listAssets(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) async throws -> [HealthReportLocalOriginalMetadata]

    /// 只读取一页原件，避免多页大报告在详情页一次进入内存。
    func loadAsset(
        workflowID: Int,
        assetIndex: Int,
        accountScope: String,
        subjectUserID: Int
    ) async throws -> HealthReportLocalOriginalAsset

    /// 返回与后端 `aggregate_asset_digest` 完全一致的本机绑定证明。
    func bindingProof(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) async throws -> HealthReportLocalOriginalBindingProof
}

/// 报告原件本地仓库。
///
/// 文件按“账号作用域 + 数字主体”分区；blob 写完并校验后才原子提交 manifest，工作流绑定也单独
/// 原子提交。这样上传失败、页面重建或 App 重启都不会丢掉用户选择的原件。
actor HealthReportLocalOriginalStore: HealthReportLocalOriginalStoreProtocol {
    static let shared = HealthReportLocalOriginalStore()

    private struct StoredAsset: Codable, Equatable, Sendable {
        let assetIndex: Int
        let fileName: String
        let mimeType: String
        let byteSize: Int
        let sha256: String
        let blobName: String
    }

    private struct Manifest: Codable, Equatable, Sendable {
        let schemaVersion: Int
        let clientRequestID: String
        let subjectUserID: Int
        var workflowID: Int?
        var assets: [StoredAsset]
    }

    private struct WorkflowBinding: Codable, Equatable, Sendable {
        let schemaVersion: Int
        let workflowID: Int
        let clientRequestID: String
        let subjectUserID: Int
    }

    private struct WorkflowBindingJournal: Codable, Equatable, Sendable {
        let schemaVersion: Int
        let workflowID: Int
        let clientRequestID: String
        let subjectUserID: Int
    }

    private struct SubjectDirectory {
        let blobs: URL
        let manifests: URL
        let workflows: URL
        let journals: URL
    }

    private let rootDirectory: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let fileProtectionPolicy: @Sendable (URL, FileManager) throws -> Void
    private let bindingCheckpoint: @Sendable (HealthReportLocalOriginalBindingCheckpoint) throws -> Void

    /// 创建本地仓库。
    /// - Parameters:
    ///   - rootDirectory: 测试可传临时目录；生产默认使用 Application Support。
    ///   - fileManager: 文件系统实现，默认使用系统实现。
    init(
        rootDirectory: URL? = nil,
        fileManager: FileManager = .default
    ) {
        self.fileManager = fileManager
        self.rootDirectory = rootDirectory ?? Self.defaultRootDirectory(fileManager: fileManager)
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
        self.fileProtectionPolicy = { url, manager in
            try Self.applyAndVerifyFileProtection(to: url, fileManager: manager)
        }
        self.bindingCheckpoint = { _ in }
    }

    /// 创建可注入文件保护校验与绑定中断点的仓库，供确定性回归使用。
    /// - Parameters:
    ///   - rootDirectory: 本地原件根目录。
    ///   - fileManager: 文件系统实现。
    ///   - fileProtectionPolicy: 必须完成属性设置并回读验证；抛错时写入失败关闭。
    ///   - bindingCheckpoint: journal、manifest、binding 各提交边界后的故障注入点。
    init(
        rootDirectory: URL?,
        fileManager: FileManager = .default,
        fileProtectionPolicy: @escaping @Sendable (URL, FileManager) throws -> Void,
        bindingCheckpoint: @escaping @Sendable (HealthReportLocalOriginalBindingCheckpoint) throws -> Void = { _ in }
    ) {
        self.fileManager = fileManager
        self.rootDirectory = rootDirectory ?? Self.defaultRootDirectory(fileManager: fileManager)
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
        self.fileProtectionPolicy = fileProtectionPolicy
        self.bindingCheckpoint = bindingCheckpoint
    }

    func persistUpload(
        inputs: [HealthReportUploadAssetInput],
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) throws {
        let identity = try validatedIdentity(
            clientRequestID: clientRequestID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        guard !inputs.isEmpty else {
            throw HealthReportLocalOriginalStoreError.invalidAsset(index: 1)
        }

        let directory = try prepareSubjectDirectory(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        var assets: [StoredAsset] = []
        assets.reserveCapacity(inputs.count)
        for (offset, input) in inputs.enumerated() {
            assets.append(
                try persistBlob(
                    input: input,
                    assetIndex: offset + 1,
                    blobsDirectory: directory.blobs
                )
            )
        }

        let manifest = Manifest(
            schemaVersion: 1,
            clientRequestID: identity.clientRequestID,
            subjectUserID: subjectUserID,
            workflowID: nil,
            assets: assets
        )
        try writeJSONAtomically(
            manifest,
            to: directory.manifests.appendingPathComponent("\(identity.requestKey).json")
        )
    }

    func persistReplacement(
        input: HealthReportUploadAssetInput,
        assetIndex: Int,
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) throws {
        guard assetIndex > 0 else {
            throw HealthReportLocalOriginalStoreError.invalidAsset(index: assetIndex)
        }
        let identity = try validatedIdentity(
            clientRequestID: clientRequestID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        let directory = try prepareSubjectDirectory(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        let manifestURL = directory.manifests.appendingPathComponent("\(identity.requestKey).json")
        var manifest = try loadManifest(
            at: manifestURL,
            clientRequestID: clientRequestID,
            subjectUserID: subjectUserID
        )
        let replacement = try persistBlob(
            input: input,
            assetIndex: assetIndex,
            blobsDirectory: directory.blobs
        )
        manifest.assets.removeAll { $0.assetIndex == assetIndex }
        manifest.assets.append(replacement)
        manifest.assets.sort { $0.assetIndex < $1.assetIndex }
        try writeJSONAtomically(manifest, to: manifestURL)
    }

    func bindWorkflow(
        workflowID: Int,
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) throws {
        guard workflowID > 0 else {
            throw HealthReportLocalOriginalStoreError.invalidIdentity
        }
        let identity = try validatedIdentity(
            clientRequestID: clientRequestID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        let directory = try prepareSubjectDirectory(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        try recoverBindingIfNeeded(
            workflowID: workflowID,
            directory: directory,
            subjectUserID: subjectUserID
        )
        let manifestURL = directory.manifests.appendingPathComponent("\(identity.requestKey).json")
        var manifest = try loadManifest(
            at: manifestURL,
            clientRequestID: clientRequestID,
            subjectUserID: subjectUserID
        )
        try validateAssets(manifest.assets, blobsDirectory: directory.blobs)
        guard manifest.workflowID == nil || manifest.workflowID == workflowID else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        try validateExistingBinding(
            workflowID: workflowID,
            clientRequestID: clientRequestID,
            subjectUserID: subjectUserID,
            candidateAssets: manifest.assets,
            directory: directory
        )

        let journal = WorkflowBindingJournal(
            schemaVersion: 1,
            workflowID: workflowID,
            clientRequestID: clientRequestID,
            subjectUserID: subjectUserID
        )
        let journalURL = directory.journals.appendingPathComponent("\(workflowID).json")
        try writeJSONAtomically(journal, to: journalURL)
        try bindingCheckpoint(.journalPersisted)

        manifest.workflowID = workflowID
        try writeJSONAtomically(manifest, to: manifestURL)
        try bindingCheckpoint(.manifestPersisted)

        let binding = WorkflowBinding(
            schemaVersion: 1,
            workflowID: workflowID,
            clientRequestID: clientRequestID,
            subjectUserID: subjectUserID
        )
        try writeJSONAtomically(
            binding,
            to: directory.workflows.appendingPathComponent("\(workflowID).json")
        )
        try bindingCheckpoint(.bindingPersisted)
        try removeJournal(at: journalURL)
    }

    func loadAssets(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) throws -> [HealthReportLocalOriginalAsset] {
        let resolved = try resolveManifest(
            workflowID: workflowID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        return try resolved.manifest.assets.sorted { $0.assetIndex < $1.assetIndex }.map { asset in
            try makeLoadedAsset(asset, blobsDirectory: resolved.directory.blobs)
        }
    }

    func listAssets(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) throws -> [HealthReportLocalOriginalMetadata] {
        let resolved = try resolveManifest(
            workflowID: workflowID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        return try resolved.manifest.assets.sorted { $0.assetIndex < $1.assetIndex }.map { asset in
            try makeMetadata(asset, blobsDirectory: resolved.directory.blobs)
        }
    }

    func loadAsset(
        workflowID: Int,
        assetIndex: Int,
        accountScope: String,
        subjectUserID: Int
    ) throws -> HealthReportLocalOriginalAsset {
        guard assetIndex > 0 else {
            throw HealthReportLocalOriginalStoreError.invalidAsset(index: assetIndex)
        }
        let resolved = try resolveManifest(
            workflowID: workflowID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        guard let stored = resolved.manifest.assets.first(where: { $0.assetIndex == assetIndex }) else {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
        return try makeLoadedAsset(stored, blobsDirectory: resolved.directory.blobs)
    }

    func bindingProof(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) throws -> HealthReportLocalOriginalBindingProof {
        let resolved = try resolveManifest(
            workflowID: workflowID,
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        let assets = try resolved.manifest.assets.sorted { $0.assetIndex < $1.assetIndex }.map { asset in
            // ACK 会授权服务端退休临时处理副本，因此不能只信任 manifest 和文件长度。
            // 每次生成证明前都重新读取真实原件并核对摘要，阻断“同长度篡改”沿用旧 SHA。
            _ = try loadValidatedBlob(asset, blobsDirectory: resolved.directory.blobs)
            return asset
        }
        return HealthReportLocalOriginalBindingProof(
            contractVersion: 1,
            clientRequestID: resolved.manifest.clientRequestID,
            assetCount: assets.count,
            aggregateSHA256: try Self.aggregateDigest(assets)
        )
    }

    private func resolveManifest(
        workflowID: Int,
        accountScope: String,
        subjectUserID: Int
    ) throws -> (manifest: Manifest, directory: SubjectDirectory) {
        guard workflowID > 0,
              subjectUserID > 0,
              !accountScope.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw HealthReportLocalOriginalStoreError.invalidIdentity
        }
        let directory = subjectDirectory(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        try recoverBindingIfNeeded(
            workflowID: workflowID,
            directory: directory,
            subjectUserID: subjectUserID
        )
        let bindingURL = directory.workflows.appendingPathComponent("\(workflowID).json")
        guard fileManager.fileExists(atPath: bindingURL.path) else {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
        let binding: WorkflowBinding = try readJSON(bindingURL)
        guard binding.schemaVersion == 1,
              binding.workflowID == workflowID,
              binding.subjectUserID == subjectUserID else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        let requestKey = Self.digest(Data(binding.clientRequestID.utf8))
        let manifest = try loadManifest(
            at: directory.manifests.appendingPathComponent("\(requestKey).json"),
            clientRequestID: binding.clientRequestID,
            subjectUserID: subjectUserID
        )
        guard manifest.workflowID == workflowID else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        return (manifest, directory)
    }

    /// journal 永远先于 manifest/binding 写入，因此任一后续边界中断都能按 workflow+request 重放。
    private func recoverBindingIfNeeded(
        workflowID: Int,
        directory: SubjectDirectory,
        subjectUserID: Int
    ) throws {
        let journalURL = directory.journals.appendingPathComponent("\(workflowID).json")
        guard fileManager.fileExists(atPath: journalURL.path) else { return }
        let journal: WorkflowBindingJournal = try readJSON(journalURL)
        guard journal.schemaVersion == 1,
              journal.workflowID == workflowID,
              journal.subjectUserID == subjectUserID,
              !journal.clientRequestID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }

        let requestKey = Self.digest(Data(journal.clientRequestID.utf8))
        let manifestURL = directory.manifests.appendingPathComponent("\(requestKey).json")
        var manifest = try loadManifest(
            at: manifestURL,
            clientRequestID: journal.clientRequestID,
            subjectUserID: subjectUserID
        )
        guard manifest.workflowID == nil || manifest.workflowID == workflowID else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        if manifest.workflowID == nil {
            manifest.workflowID = workflowID
            try writeJSONAtomically(manifest, to: manifestURL)
        }

        try validateExistingBinding(
            workflowID: workflowID,
            clientRequestID: journal.clientRequestID,
            subjectUserID: subjectUserID,
            candidateAssets: manifest.assets,
            directory: directory
        )
        let bindingURL = directory.workflows.appendingPathComponent("\(workflowID).json")
        try writeJSONAtomically(
            WorkflowBinding(
                schemaVersion: 1,
                workflowID: workflowID,
                clientRequestID: journal.clientRequestID,
                subjectUserID: subjectUserID
            ),
            to: bindingURL
        )
        try removeJournal(at: journalURL)
    }

    private func validateExistingBinding(
        workflowID: Int,
        clientRequestID: String,
        subjectUserID: Int,
        candidateAssets: [StoredAsset],
        directory: SubjectDirectory
    ) throws {
        let bindingURL = directory.workflows.appendingPathComponent("\(workflowID).json")
        guard fileManager.fileExists(atPath: bindingURL.path) else { return }
        let binding: WorkflowBinding = try readJSON(bindingURL)
        guard binding.schemaVersion == 1,
              binding.workflowID == workflowID,
              binding.subjectUserID == subjectUserID else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        guard binding.clientRequestID != clientRequestID else { return }

        // 精确重复上传会合法复用既有 workflow；仅当旧、新本机副本的聚合摘要完全一致时允许换绑。
        let existingRequestKey = Self.digest(Data(binding.clientRequestID.utf8))
        let existingManifest = try loadManifest(
            at: directory.manifests.appendingPathComponent("\(existingRequestKey).json"),
            clientRequestID: binding.clientRequestID,
            subjectUserID: subjectUserID
        )
        guard existingManifest.workflowID == workflowID,
              existingManifest.assets.count == candidateAssets.count,
              try Self.aggregateDigest(existingManifest.assets)
                == Self.aggregateDigest(candidateAssets) else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
    }

    private func removeJournal(at url: URL) throws {
        guard fileManager.fileExists(atPath: url.path) else { return }
        do {
            try fileManager.removeItem(at: url)
        } catch {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }
    }

    private func validatedIdentity(
        clientRequestID: String,
        accountScope: String,
        subjectUserID: Int
    ) throws -> (clientRequestID: String, requestKey: String) {
        let requestID = clientRequestID.trimmingCharacters(in: .whitespacesAndNewlines)
        let scope = accountScope.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !requestID.isEmpty, !scope.isEmpty, subjectUserID > 0 else {
            throw HealthReportLocalOriginalStoreError.invalidIdentity
        }
        return (requestID, Self.digest(Data(requestID.utf8)))
    }

    private func prepareSubjectDirectory(
        accountScope: String,
        subjectUserID: Int
    ) throws -> SubjectDirectory {
        let directory = subjectDirectory(
            accountScope: accountScope,
            subjectUserID: subjectUserID
        )
        do {
            for url in [directory.blobs, directory.manifests, directory.workflows, directory.journals] {
                try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
                try applyLocalProtection(to: url)
            }
            return directory
        } catch {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }
    }

    private func subjectDirectory(
        accountScope: String,
        subjectUserID: Int
    ) -> SubjectDirectory {
        let accountKey = Self.digest(Data(accountScope.utf8))
        let base = rootDirectory
            .appendingPathComponent("accounts", isDirectory: true)
            .appendingPathComponent(accountKey, isDirectory: true)
            .appendingPathComponent("subjects", isDirectory: true)
            .appendingPathComponent(String(subjectUserID), isDirectory: true)
        return SubjectDirectory(
            blobs: base.appendingPathComponent("blobs", isDirectory: true),
            manifests: base.appendingPathComponent("manifests", isDirectory: true),
            workflows: base.appendingPathComponent("workflows", isDirectory: true),
            journals: base.appendingPathComponent("binding-journals", isDirectory: true)
        )
    }

    private func persistBlob(
        input: HealthReportUploadAssetInput,
        assetIndex: Int,
        blobsDirectory: URL
    ) throws -> StoredAsset {
        guard assetIndex > 0, !input.data.isEmpty else {
            throw HealthReportLocalOriginalStoreError.invalidAsset(index: assetIndex)
        }
        let sha256 = Self.digest(input.data)
        let blobName = "\(sha256).original"
        let blobURL = blobsDirectory.appendingPathComponent(blobName)
        do {
            if fileManager.fileExists(atPath: blobURL.path) {
                let existing = try LocalFileDataLoader.read(blobURL, options: .mappedIfSafe)
                guard existing.count == input.data.count,
                      Self.digest(existing) == sha256 else {
                    throw HealthReportLocalOriginalStoreError.integrityMismatch(index: assetIndex)
                }
            } else {
                try input.data.write(to: blobURL, options: [.atomic, .completeFileProtection])
                let written = try LocalFileDataLoader.read(blobURL, options: .mappedIfSafe)
                guard written.count == input.data.count,
                      Self.digest(written) == sha256 else {
                    throw HealthReportLocalOriginalStoreError.integrityMismatch(index: assetIndex)
                }
            }
            try applyLocalProtection(to: blobURL)
        } catch let error as HealthReportLocalOriginalStoreError {
            throw error
        } catch {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }

        return StoredAsset(
            assetIndex: assetIndex,
            fileName: Self.safeDisplayName(input.fileName, index: assetIndex),
            mimeType: MIMETypeHelper.mimeType(forFileName: input.fileName),
            byteSize: input.data.count,
            sha256: sha256,
            blobName: blobName
        )
    }

    private func loadManifest(
        at url: URL,
        clientRequestID: String,
        subjectUserID: Int
    ) throws -> Manifest {
        guard fileManager.fileExists(atPath: url.path) else {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
        let manifest: Manifest = try readJSON(url)
        guard manifest.schemaVersion == 1,
              manifest.clientRequestID == clientRequestID,
              manifest.subjectUserID == subjectUserID,
              !manifest.assets.isEmpty,
              Set(manifest.assets.map(\.assetIndex)).count == manifest.assets.count,
              manifest.assets.allSatisfy({ $0.assetIndex > 0 }) else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        return manifest
    }

    private func validateAssets(
        _ assets: [StoredAsset],
        blobsDirectory: URL
    ) throws {
        for asset in assets {
            _ = try loadValidatedBlob(asset, blobsDirectory: blobsDirectory)
        }
    }

    private func loadValidatedBlob(
        _ asset: StoredAsset,
        blobsDirectory: URL
    ) throws -> Data {
        let url = blobsDirectory.appendingPathComponent(asset.blobName)
        guard fileManager.fileExists(atPath: url.path) else {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
        do {
            try applyLocalProtection(to: url)
            let data = try LocalFileDataLoader.read(url, options: .mappedIfSafe)
            guard data.count == asset.byteSize,
                  Self.digest(data) == asset.sha256,
                  asset.blobName == "\(asset.sha256).original" else {
                throw HealthReportLocalOriginalStoreError.integrityMismatch(index: asset.assetIndex)
            }
            return data
        } catch let error as HealthReportLocalOriginalStoreError {
            throw error
        } catch {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
    }

    private func makeMetadata(
        _ asset: StoredAsset,
        blobsDirectory: URL
    ) throws -> HealthReportLocalOriginalMetadata {
        guard asset.blobName == "\(asset.sha256).original",
              asset.assetIndex > 0,
              asset.byteSize > 0 else {
            throw HealthReportLocalOriginalStoreError.integrityMismatch(index: asset.assetIndex)
        }
        let url = blobsDirectory.appendingPathComponent(asset.blobName)
        guard fileManager.fileExists(atPath: url.path) else {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
        do {
            try applyLocalProtection(to: url)
            let attributes = try fileManager.attributesOfItem(atPath: url.path)
            guard attributes[.type] as? FileAttributeType == .typeRegular,
                  let size = attributes[.size] as? NSNumber,
                  size.intValue == asset.byteSize else {
                throw HealthReportLocalOriginalStoreError.integrityMismatch(index: asset.assetIndex)
            }
            return HealthReportLocalOriginalMetadata(
                assetIndex: asset.assetIndex,
                fileName: asset.fileName,
                mimeType: asset.mimeType,
                byteSize: asset.byteSize,
                sha256: asset.sha256
            )
        } catch let error as HealthReportLocalOriginalStoreError {
            throw error
        } catch {
            throw HealthReportLocalOriginalStoreError.reportNotFound
        }
    }

    private func makeLoadedAsset(
        _ asset: StoredAsset,
        blobsDirectory: URL
    ) throws -> HealthReportLocalOriginalAsset {
        HealthReportLocalOriginalAsset(
            assetIndex: asset.assetIndex,
            fileName: asset.fileName,
            mimeType: asset.mimeType,
            byteSize: asset.byteSize,
            sha256: asset.sha256,
            data: try loadValidatedBlob(asset, blobsDirectory: blobsDirectory)
        )
    }

    private func writeJSONAtomically<T: Encodable>(_ value: T, to url: URL) throws {
        do {
            let data = try encoder.encode(value)
            try data.write(to: url, options: [.atomic, .completeFileProtection])
            try applyLocalProtection(to: url)
        } catch {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }
    }

    private func readJSON<T: Decodable>(_ url: URL) throws -> T {
        do {
            try applyLocalProtection(to: url)
        } catch {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }
        do {
            return try decoder.decode(T.self, from: LocalFileDataLoader.read(url))
        } catch {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
    }

    private func applyLocalProtection(to url: URL) throws {
        try fileProtectionPolicy(url, fileManager)
    }

    /// 设置后立即回读两个本地隐私属性；任何不支持或不一致都失败关闭，不静默降级。
    nonisolated private static func applyAndVerifyFileProtection(
        to url: URL,
        fileManager: FileManager
    ) throws {
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.complete],
            ofItemAtPath: url.path
        )
        let attributes = try fileManager.attributesOfItem(atPath: url.path)
        guard attributes[.protectionKey] as? FileProtectionType == .complete else {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var protectedURL = url
        try protectedURL.setResourceValues(values)
        let verified = try protectedURL.resourceValues(forKeys: [.isExcludedFromBackupKey])
        guard verified.isExcludedFromBackup == true else {
            throw HealthReportLocalOriginalStoreError.writeFailed
        }
    }

    nonisolated private static func defaultRootDirectory(fileManager: FileManager) -> URL {
        guard let base = fileManager.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else {
            // Application Support 不可用时刻意指向不可创建路径，后续写入失败关闭；绝不降级到临时目录。
            return URL(fileURLWithPath: "/dev/null/HealthReportOriginals", isDirectory: true)
        }
        return base.appendingPathComponent("HealthReportOriginals", isDirectory: true)
    }

    nonisolated private static func safeDisplayName(_ value: String, index: Int) -> String {
        let name = (value as NSString).lastPathComponent
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return name.isEmpty ? "报告原件-\(index)" : String(name.prefix(180))
    }

    nonisolated private static func digest(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// 与后端 `aggregate_asset_digest` 一致：单页直接复用页摘要，多页按稳定二进制 framing 聚合。
    nonisolated private static func aggregateDigest(_ assets: [StoredAsset]) throws -> String {
        guard !assets.isEmpty else {
            throw HealthReportLocalOriginalStoreError.corruptManifest
        }
        if assets.count == 1 {
            guard hexBytes(assets[0].sha256)?.count == 32 else {
                throw HealthReportLocalOriginalStoreError.corruptManifest
            }
            return assets[0].sha256
        }

        var payload = Data("xjie-report-asset-set-v1\0".utf8)
        for asset in assets {
            guard let index = UInt32(exactly: asset.assetIndex),
                  let byteSize = UInt64(exactly: asset.byteSize),
                  let shaBytes = hexBytes(asset.sha256),
                  shaBytes.count == 32 else {
                throw HealthReportLocalOriginalStoreError.corruptManifest
            }
            let mimeBytes = Data(asset.mimeType.utf8)
            guard let mimeLength = UInt16(exactly: mimeBytes.count) else {
                throw HealthReportLocalOriginalStoreError.corruptManifest
            }
            appendBigEndian(index, to: &payload)
            appendBigEndian(byteSize, to: &payload)
            appendBigEndian(mimeLength, to: &payload)
            payload.append(mimeBytes)
            payload.append(contentsOf: shaBytes)
        }
        return digest(payload)
    }

    nonisolated private static func appendBigEndian<T: FixedWidthInteger>(
        _ value: T,
        to data: inout Data
    ) {
        var bigEndian = value.bigEndian
        Swift.withUnsafeBytes(of: &bigEndian) { bytes in
            data.append(contentsOf: bytes)
        }
    }

    nonisolated private static func hexBytes(_ value: String) -> [UInt8]? {
        guard value.count.isMultiple(of: 2) else { return nil }
        var bytes: [UInt8] = []
        bytes.reserveCapacity(value.count / 2)
        var index = value.startIndex
        while index < value.endIndex {
            let next = value.index(index, offsetBy: 2)
            guard let byte = UInt8(value[index..<next], radix: 16) else { return nil }
            bytes.append(byte)
            index = next
        }
        return bytes
    }
}
