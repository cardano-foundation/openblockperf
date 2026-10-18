//! Calidus signing key load + Ed25519 challenge signature.

use anyhow::{anyhow, Context, Result};
use ed25519_dalek::{Signer, SigningKey};
use serde_json::Value;
use std::path::Path;

pub fn parse_key_file(path: &Path) -> Result<Value> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("Path not found: {}", path.display()))?;
    Ok(serde_json::from_str(&raw)?)
}

/// Extract 32-byte Ed25519 seed from Cardano extended signing key CBOR hex.
///
/// Matches the Python path: CBOR-decode `cborHex`, then take the first 32 bytes
/// of the extended private key material.
pub fn extract_signing_key_from_cbor(cbor_hex: &str) -> Result<SigningKey> {
    let bytes = hex::decode(cbor_hex.trim()).context("cborHex is not valid hex")?;
    let value: ciborium::Value =
        ciborium::from_reader(bytes.as_slice()).context("cborHex is not valid CBOR")?;
    let raw = match value {
        ciborium::Value::Bytes(b) => b,
        _ => return Err(anyhow!("expected CBOR bytes for signing key")),
    };
    if raw.len() < 32 {
        return Err(anyhow!("signing key material too short ({})", raw.len()));
    }
    let mut seed = [0u8; 32];
    seed.copy_from_slice(&raw[..32]);
    Ok(SigningKey::from_bytes(&seed))
}

pub fn sign_challenge(signing_key: &SigningKey, challenge: &str) -> String {
    let sig = signing_key.sign(challenge.as_bytes());
    hex::encode(sig.to_bytes())
}

pub fn sign_challenge_from_skey_file(path: &Path, challenge: &str) -> Result<String> {
    let doc = parse_key_file(path)?;
    let cbor_hex = doc
        .get("cborHex")
        .and_then(|v| v.as_str())
        .ok_or_else(|| anyhow!("skey missing cborHex"))?;
    let key = extract_signing_key_from_cbor(cbor_hex)?;
    Ok(sign_challenge(&key, challenge))
}
