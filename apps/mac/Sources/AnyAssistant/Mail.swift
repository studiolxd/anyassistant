// Mail accounts besides Gmail (the plugin «mail», through /admin/mail, only from the Mac):
// add one (the servers guessed, tried before saving), import the Mac's own (Internet
// Accounts: their servers; the password you type, macOS keeps its own to itself), try, remove.
// The password goes to the Keychain, never to settings.json.

import AppKit
import SwiftUI

struct MailAccount: Identifiable, Equatable {
    var id: String { address }
    let name: String
    let address: String
    let imap: String
    let smtp: String
    let user: String
    let password: Bool

    init(_ raw: [String: Any]) {
        name = raw["name"] as? String ?? ""
        address = raw["address"] as? String ?? ""
        imap = raw["imap"] as? String ?? ""
        smtp = raw["smtp"] as? String ?? ""
        user = raw["user"] as? String ?? ""
        password = raw["password"] as? Bool ?? false
    }
}

@MainActor
final class MailAccounts: ObservableObject {
    @Published var accounts: [MailAccount] = []
    @Published var onTheMac: [MailAccount]?  // the Mac's own, once asked for
    @Published var needsDiskAccess = false
    @Published var off = false  // the plugin «mail» is off
    @Published var busy: String?  // the address being tried
    @Published var problems: [String: [String]] = [:]  // per address, what failed
    @Published var fine: Set<String> = []  // tried and working

    let server = Server.shared

    private func call(_ query: String = "", _ body: [String: Any]? = nil) async -> (Int, [String: Any]) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(server.port)/admin/mail\(query)")!)
        request.timeoutInterval = 60  // trying the servers takes a while
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (raw, response) = try? await URLSession.shared.data(for: request) else { return (0, [:]) }
        let answer = (try? JSONSerialization.jsonObject(with: raw) as? [String: Any]) ?? [:]
        return ((response as? HTTPURLResponse)?.statusCode ?? 0, answer)
    }

    private func show(_ answer: [String: Any]) {
        if let found = answer["accounts"] as? [[String: Any]] { accounts = found.map(MailAccount.init) }
    }

    func load() async {
        let (status, answer) = await call()
        off = status == 404
        show(answer)
    }

    func guess(_ address: String) async -> (String, String)? {
        guard address.contains("@"),
              let query = address.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) else { return nil }
        let (status, answer) = await call("?guess=\(query)")
        guard status == 200 else { return nil }
        return (answer["imap"] as? String ?? "", answer["smtp"] as? String ?? "")
    }

    /// Tries it and saves it; true if it works.
    func add(address: String, password: String, name: String = "", imap: String = "", smtp: String = "",
             user: String = "") async -> Bool {
        busy = address
        defer { busy = nil }
        let (status, answer) = await call("", ["add": ["address": address, "password": password, "name": name,
                                                       "imap": imap, "smtp": smtp, "user": user]])
        if status == 200 {
            problems[address] = nil
            show(answer)
            onTheMac?.removeAll { $0.address == address }
            return true
        }
        problems[address] = answer["problems"] as? [String]
            ?? [answer["error"] as? String ?? T("The server isn't answering: is it running?")]
        return false
    }

    func test(_ account: MailAccount) async {
        busy = account.address
        defer { busy = nil }
        let (_, answer) = await call("", ["test": account.address])
        let found = answer["problems"] as? [String] ?? []
        problems[account.address] = found.isEmpty ? nil : found
        if found.isEmpty { fine.insert(account.address) } else { fine.remove(account.address) }
    }

    func remove(_ account: MailAccount) async {
        let (_, answer) = await call("", ["remove": account.address])
        show(answer)
    }

    func importFromTheMac() async {
        let (status, answer) = await call("?mac=1")
        needsDiskAccess = status == 403
        onTheMac = (answer["accounts"] as? [[String: Any]] ?? []).map(MailAccount.init)
    }
}

struct MailView: View {
    @StateObject private var mail = MailAccounts()
    @State private var address = ""
    @State private var name = ""
    @State private var password = ""
    @State private var imap = ""
    @State private var smtp = ""
    @State private var user = ""

    var body: some View {
        Form {
            if mail.off {
                Text(T("Turn on the plugin «Mail (IMAP and SMTP)» to add accounts besides Gmail."))
                    .foregroundStyle(.secondary)
            } else {
                Section {
                    if mail.accounts.isEmpty {
                        Text(T("No accounts yet. Gmail doesn't go here: it works through Google (gog).")).foregroundStyle(.secondary)
                    }
                    ForEach(mail.accounts) { account in
                        accountRow(account)
                    }
                } header: {
                    Text(T("Accounts"))
                } footer: {
                    Text(T("New emails get a notice, the morning summary counts them, and the assistant can read them and send (with your «yes»). The password is kept in the Keychain."))
                        .font(.caption).foregroundStyle(.secondary)
                }
                Section(T("Add an account")) {
                    TextField(T("Address"), text: $address, prompt: Text("tu@dominio.com"))
                        .onChange(of: address) { _, now in Task { await fill(now) } }
                    TextField(T("Name"), text: $name, prompt: Text(T("as you'll call it: «Trabajo»")))
                    SecureField(T("Password"), text: $password, prompt: Text(T("an app password, if your provider has them")))
                    DisclosureGroup(T("Servers")) {
                        TextField("IMAP", text: $imap, prompt: Text("imap.dominio.com:993"))
                        TextField("SMTP", text: $smtp, prompt: Text("smtp.dominio.com:465"))
                        TextField(T("Login"), text: $user, prompt: Text(T("the address")))
                    }
                    problemsOf(address)
                    HStack {
                        Spacer()
                        if mail.busy == address && !address.isEmpty { ProgressView().controlSize(.small) }
                        Button(T("Try and add")) {
                            Task {
                                if await mail.add(address: address, password: password, name: name, imap: imap,
                                                  smtp: smtp, user: user) {
                                    address = ""; name = ""; password = ""; imap = ""; smtp = ""; user = ""
                                }
                            }
                        }
                        .disabled(!address.contains("@") || password.isEmpty || mail.busy != nil)
                    }
                }
                Section {
                    if let found = mail.onTheMac {
                        if mail.needsDiskAccess {
                            Text(T("To read the Mac's accounts, AnyAssistant needs Full Disk Access (System Settings → Privacy & Security), then restart it."))
                            Button(T("Open Privacy & Security")) {
                                NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles")!)
                            }
                        } else if found.isEmpty {
                            Text(T("No IMAP accounts on this Mac that aren't here already.")).foregroundStyle(.secondary)
                        }
                        ForEach(found) { account in
                            ImportRow(account: account, mail: mail)
                        }
                    } else {
                        Button(T("Import from this Mac…")) { Task { await mail.importFromTheMac() } }
                    }
                } header: {
                    Text(T("The Mac's accounts"))
                } footer: {
                    Text(T("Their servers come from Internet Accounts; macOS doesn't share their passwords, so you type each one. Exchange, Google and iCloud accounts aren't here."))
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
        }
        .formStyle(.grouped)
        .task { await mail.load() }
    }

    func fill(_ now: String) async {
        guard let (foundImap, foundSmtp) = await mail.guess(now), now == address else { return }
        imap = foundImap
        smtp = foundSmtp
    }

    @ViewBuilder func problemsOf(_ address: String) -> some View {
        ForEach(mail.problems[address] ?? [], id: \.self) { problem in
            Text(problem).font(.caption).foregroundStyle(.red).textSelection(.enabled)
        }
    }

    func accountRow(_ account: MailAccount) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(account.name).font(.body.weight(.medium))
                    Text(account.address).font(.caption).foregroundStyle(.secondary)
                    Text("IMAP \(account.imap) · SMTP \(account.smtp)").font(.caption2).foregroundStyle(.tertiary)
                }
                Spacer()
                if !account.password {
                    Text(T("No password")).font(.caption).foregroundStyle(.red)
                } else if mail.fine.contains(account.address) {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                }
                if mail.busy == account.address { ProgressView().controlSize(.small) }
                Button(T("Try")) { Task { await mail.test(account) } }.disabled(mail.busy != nil)
                Button(T("Remove")) { Task { await mail.remove(account) } }.foregroundStyle(.red)
            }
            problemsOf(account.address)
        }
    }
}

/// One of the Mac's accounts: its password, and it's tried and added.
struct ImportRow: View {
    let account: MailAccount
    @ObservedObject var mail: MailAccounts
    @State private var password = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(account.address)
                    Text("IMAP \(account.imap) · SMTP \(account.smtp)").font(.caption2).foregroundStyle(.tertiary)
                }
                Spacer()
                SecureField(T("Password"), text: $password).labelsHidden().frame(width: 180)
                if mail.busy == account.address { ProgressView().controlSize(.small) }
                Button(T("Add")) {
                    Task {
                        _ = await mail.add(address: account.address, password: password, name: account.name,
                                           imap: account.imap, smtp: account.smtp, user: account.user)
                    }
                }
                .disabled(password.isEmpty || mail.busy != nil)
            }
            ForEach(mail.problems[account.address] ?? [], id: \.self) { problem in
                Text(problem).font(.caption).foregroundStyle(.red).textSelection(.enabled)
            }
        }
    }
}
