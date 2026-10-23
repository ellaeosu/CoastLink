// Release signing for CoastLink updates (not shipped with the app).
//   coastlink-sign keygen <private key file>          new ed25519 key; prints the public key (launcher/update_pubkey.txt)
//   coastlink-sign sign <private key file> <file>      prints the base64 signature of <file> (<manifest>.sig)
//   coastlink-sign verify <public key b64> <file> <sig b64>
// The private key file holds the 32-byte seed in base64. Keep it out of the repository. GPL-3.0-or-later.
use base64::Engine as _;
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};

fn b64() -> base64::engine::GeneralPurpose {
    base64::engine::general_purpose::STANDARD
}

fn load(path: &str) -> SigningKey {
    let text = std::fs::read_to_string(path).expect("cannot read the private key file");
    let seed: [u8; 32] = b64().decode(text.trim()).expect("bad key file").try_into().expect("bad key length");
    SigningKey::from_bytes(&seed)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    match args.get(1).map(String::as_str) {
        Some("keygen") if args.len() == 3 => {
            let path = &args[2];
            if std::path::Path::new(path).exists() {
                eprintln!("{path} exists; not overwriting a signing key");
                std::process::exit(2);
            }
            let mut seed = [0u8; 32];
            getrandom::getrandom(&mut seed).expect("no system randomness");
            std::fs::write(path, b64().encode(seed)).expect("cannot write the key file");
            println!("{}", b64().encode(SigningKey::from_bytes(&seed).verifying_key().to_bytes()));
        }
        Some("sign") if args.len() == 4 => {
            let data = std::fs::read(&args[3]).expect("cannot read the file");
            println!("{}", b64().encode(load(&args[2]).sign(&data).to_bytes()));
        }
        Some("verify") if args.len() == 5 => {
            let key: [u8; 32] = b64().decode(args[2].trim()).expect("bad key").try_into().expect("bad key length");
            let key = VerifyingKey::from_bytes(&key).expect("bad key");
            let data = std::fs::read(&args[3]).expect("cannot read the file");
            let sig = Signature::from_slice(&b64().decode(args[4].trim()).expect("bad signature")).expect("bad signature");
            let ok = key.verify(&data, &sig).is_ok();
            println!("{}", if ok { "valid" } else { "INVALID" });
            std::process::exit(if ok { 0 } else { 1 });
        }
        _ => {
            eprintln!("usage: coastlink-sign keygen <key file> | sign <key file> <file> | verify <public key> <file> <signature>");
            std::process::exit(2);
        }
    }
}
