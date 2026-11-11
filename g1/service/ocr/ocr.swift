import Foundation
import PDFKit
import Vision
import CoreGraphics

// ocrkit <pdf> [dpi]
// 输出 {"pages":[{"page":1,"width":W,"height":H,"words":[{t,x,y,w,h}],"lines":[...]}]}
let args = CommandLine.arguments
guard args.count >= 2 else { FileHandle.standardError.write("usage: ocrkit <pdf> [dpi]\n".data(using:.utf8)!); exit(2) }
let url = URL(fileURLWithPath: args[1])
let dpi = args.count > 2 ? (Double(args[2]) ?? 300) : 300
guard let doc = PDFDocument(url: url) else { exit(3) }

var pages: [[String: Any]] = []
for i in 0..<doc.pageCount {
    guard let page = doc.page(at: i) else { continue }
    let rect = page.bounds(for: .mediaBox)
    let scale = CGFloat(dpi / 72.0)
    let pw = Int(rect.width * scale), ph = Int(rect.height * scale)
    guard let ctx = CGContext(data: nil, width: pw, height: ph, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: CGFloat(pw), height: CGFloat(ph)))
    ctx.scaleBy(x: scale, y: scale)
    ctx.translateBy(x: -rect.origin.x, y: -rect.origin.y)
    page.draw(with: .mediaBox, to: ctx)
    guard let img = ctx.makeImage() else { continue }

    let req = VNRecognizeTextRequest()
    req.recognitionLevel = .accurate
    req.recognitionLanguages = ["zh-Hans", "en-US"]
    req.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: img, options: [:])
    do { try handler.perform([req]) } catch { continue }

    struct W { let t: String; let x: Double; let y: Double; let w: Double; let h: Double }
    var words: [W] = []
    for case let o as VNRecognizedTextObservation in (req.results ?? []) {
        guard let top = o.topCandidates(1).first else { continue }
        let t = top.string.trimmingCharacters(in: .whitespaces)
        if t.isEmpty { continue }
        let bb = o.boundingBox
        let x = Double(bb.minX) * Double(pw)
        let y = (1.0 - Double(bb.maxY)) * Double(ph)   // 转成左上原点
        words.append(W(t: t, x: x, y: y, w: Double(bb.width) * Double(pw), h: Double(bb.height) * Double(ph)))
    }
    // 行：按 y 聚类
    words.sort { $0.y < $1.y }
    var lines: [String] = []
    var bucket: [W] = []
    var lastY = -100.0
    func flush() {
        if bucket.isEmpty { return }
        lines.append(bucket.sorted { $0.x < $1.x }.map(\.t).joined())
        bucket.removeAll()
    }
    for w in words {
        if abs(w.y - lastY) > 6 { flush(); lastY = w.y }
        bucket.append(w)
    }
    flush()

    pages.append([
        "page": i + 1, "width": pw, "height": ph, "lines": lines,
        "words": words.map { ["t": $0.t, "x": $0.x, "y": $0.y, "w": $0.w, "h": $0.h] },
    ])
}
let data = try! JSONSerialization.data(withJSONObject: ["pages": pages], options: [])
FileHandle.standardOutput.write(data)
