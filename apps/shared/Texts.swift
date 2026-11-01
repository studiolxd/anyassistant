// The apps' texts, in the device's language (Resources/<lang>.lproj/Localizable.strings of each
// app; the English is the key).

import Foundation

func T(_ key: String) -> String { NSLocalizedString(key, comment: "") }
