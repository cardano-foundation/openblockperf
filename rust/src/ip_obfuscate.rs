//! Obfuscate private / allowlisted IPs before API submit.

use std::net::IpAddr;

pub fn should_obfuscate(addr: &str, allowlist: &[String]) -> bool {
    if allowlist.iter().any(|a| a == addr) {
        return true;
    }
    match addr.parse::<IpAddr>() {
        Ok(IpAddr::V4(v4)) => v4.is_private() || v4.is_loopback() || v4.is_link_local(),
        Ok(IpAddr::V6(v6)) => v6.is_loopback() || v6.is_unicast_link_local(),
        Err(_) => false,
    }
}

pub fn obfuscate_addr(addr: &str, allowlist: &[String]) -> String {
    if should_obfuscate(addr, allowlist) {
        "0.0.0.0".into()
    } else {
        addr.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn private_and_allowlist() {
        assert!(should_obfuscate("10.0.0.1", &[]));
        assert!(should_obfuscate("127.0.0.1", &[]));
        assert!(!should_obfuscate("8.8.8.8", &[]));
        assert!(should_obfuscate("8.8.8.8", &["8.8.8.8".into()]));
        assert_eq!(obfuscate_addr("192.168.1.1", &[]), "0.0.0.0");
    }
}
