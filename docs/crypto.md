---
icon: lucide/lock
---

# Cryptography

The modules under `stdlib/crypto/` are the pieces TLS 1.3 is built from,
written in Kod: hashes, HMAC and HKDF, two AEAD ciphers, a key exchange,
checking RSA and ECDSA signatures and certificates, and the operating system's
random numbers. Each is checked against the test vectors
of the standard that defines it.

```kod
import "crypto/sha2"
import "crypto/hmac"
import "encoding/hex"

print(hex.encode(sha2.sha256(b"abc")))
// ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad

let tag = hmac.mac(.Sha256, key: b"key", data: b"The quick brown fox")
```

The code that handles secrets (the ciphers, the MAC, the key exchange, ECDSA
signing and `hmac.equal`) does the same work whatever the secret is: it doesn't branch on a
secret or use one to pick an array element. That is how it keeps secrets from
showing in how long it takes. Checking a signature uses only public values, so
that code doesn't need to. None of it has been audited.

## Hashes: `crypto/sha2`

SHA-256, SHA-384 and SHA-512 (FIPS 180-4), named by `sha2.Algo`:

| `Algo` | Digest | Block |
|---|---|---|
| `.Sha256` | 32 bytes | 64 bytes |
| `.Sha384` | 48 bytes | 128 bytes |
| `.Sha512` | 64 bytes | 128 bytes |

`algo.size()` and `algo.block_size()` give the two numbers.

| Function | Gives |
|---|---|
| `sha256(data: bytes) -> bytes` | the SHA-256 digest of `data`; `sha384` and `sha512` likewise |
| `digest(algo: Algo, data: bytes) -> bytes` | the digest of `data` with `algo` |

A `Hasher` takes the data in pieces:

```kod
mut h = sha2.Hasher(.Sha384)
h.update(b"hello, ")
let so_far = h.finish()      // the digest of "hello, "
h.update(b"world")
assert h.finish() == sha2.sha384(b"hello, world")
```

`finish` doesn't change the hasher, so it can be asked for the digest of what it
has seen so far and go on; a copy (`let saved = h`) goes on from the same point
separately. TLS uses both to hash the handshake as it goes.

## HMAC: `crypto/hmac`

| Function | Gives |
|---|---|
| `mac(algo: Algo, key: bytes, data: bytes) -> bytes` | the HMAC (RFC 2104) of `data` under `key`, as long as `algo`'s digest |
| `equal(a: bytes, b: bytes) -> bool` | whether `a` and `b` are the same, taking as long for any two values of one length |

Compare a MAC with `equal`, not `==`: `==` stops at the first byte that
differs, which tells someone timing it how much of a forged MAC was right.

## HKDF: `crypto/hkdf`

HKDF (RFC 5869) makes keys from a shared secret:

| Function | Gives |
|---|---|
| `extract(algo: Algo, salt: bytes, ikm: bytes) -> bytes` | a pseudorandom key from the input key material `ikm`; an empty `salt` stands for a block of zeros |
| `expand(algo: Algo, prk: bytes, info: bytes, length: int64) -> bytes` | `length` bytes of key from `prk`, labelled by `info`; `length` is at most 255 digests, and more panics |

## ChaCha20-Poly1305: `crypto/chacha20poly1305`

The AEAD of RFC 8439: it encrypts and authenticates a message, and
authenticates extra data sent alongside it in the clear (`aad`).

<!-- kod:
import "crypto/random"
let key = random.secure_bytes(32)
let nonce = random.secure_bytes(12)
-->
```kod
import "crypto/chacha20poly1305"

let sealed = chacha20poly1305.seal(b"attack at dawn", key: key, nonce: nonce, aad: b"header")
let opened = chacha20poly1305.open(sealed, key: key, nonce: nonce, aad: b"header")   // bytes?
```

| Function | Gives |
|---|---|
| `seal(plaintext: bytes, key: bytes, nonce: bytes, aad: bytes) -> bytes` | the ciphertext, as long as `plaintext`, then the 16-byte tag |
| `open(sealed: bytes, key: bytes, nonce: bytes, aad: bytes) -> bytes?` | the plaintext, or `none` when the tag doesn't match: the data, `aad`, key or nonce isn't what was sealed |

The key is 32 bytes and the nonce 12; another length panics. A nonce must never
be used twice with one key: that gives away both messages and lets anyone forge
others. TLS counts records for it.

The two halves are there on their own too: `chacha20(data, key:, nonce:,
counter:)` XORs `data` with the key stream from block `counter`, and
`poly1305(data, key:)` is the one-time MAC under a 32-byte key.

## AES-GCM: `crypto/aesgcm`

AES-128 and AES-256 in Galois/Counter Mode (NIST SP 800-38D), the AEAD every
TLS 1.3 server has. It works as ChaCha20-Poly1305 does, with a key of 16 or 32
bytes and a nonce of 12:

<!-- kod:
import "crypto/random"
let nonce = random.secure_bytes(12)
-->
```kod
import "crypto/aesgcm"
import "crypto/random"

let key = aesgcm.Key(random.secure_bytes(16))
let sealed = key.seal(b"attack at dawn", nonce: nonce, aad: b"header")
let opened = key.open(sealed, nonce: nonce, aad: b"header")   // bytes?
```

A `Key` holds the expanded key, so a connection makes it once and seals each
record with it; `aesgcm.seal(plaintext, key:, nonce:, aad:)` and
`aesgcm.open(sealed, key:, nonce:, aad:)` make one for a single message.
`encrypt_block(block, key:)` is AES itself, on one 16-byte block.

The AES rounds and GHASH's multiplications are the CPU's own instructions
(`aese`, `aesmc` and `pmull`, which every 64-bit Apple CPU has), so they take
the same time whatever the key and data are, and AES-GCM is about seven times
as fast as ChaCha20-Poly1305 here.

## X25519: `crypto/x25519`

The Diffie-Hellman function of RFC 7748. Each side makes a private key of 32
random bytes and sends its public key; each then gets the same shared secret
from its own private key and the other's public key.

```kod
import "crypto/random"
import "crypto/x25519"

let mine = random.secure_bytes(32)
let public = x25519.public_key(mine)
// ... send `public`, receive `theirs` ...
let Some(secret) = x25519.shared(mine, theirs) else { return ... }
```

| Function | Gives |
|---|---|
| `public_key(private: bytes) -> bytes` | the 32-byte public key of a 32-byte private key |
| `shared(private: bytes, peer: bytes) -> bytes?` | the 32-byte shared secret, or `none` when it comes out all zeros, which a peer sending a bad public key causes and TLS must refuse |
| `scalar_mult(scalar: bytes, point: bytes) -> bytes` | the function itself, with no check |

A key of another length panics. One call takes about 0.16 ms (OpenSSL's,
0.023 ms), the same steps whatever the private key is.

## RSA signatures: `crypto/rsa`

`rsa.PublicKey(n:, e:)` is a key from its modulus and exponent, big-endian
bytes as a certificate holds them; a modulus under 512 bits, an even one, or an
exponent that is even or 1 is an error. Two kinds of signature are checked
(RFC 8017):

| Function | Gives |
|---|---|
| `verify_pkcs1(key: PublicKey, algo: Algo, message: bytes, signature: bytes) -> bool` | whether `signature` is the key's PKCS #1 v1.5 signature of `message` hashed with `algo`, the kind most certificates carry |
| `verify_pss(key: PublicKey, algo: Algo, message: bytes, signature: bytes, salt_size: int64 = -1) -> bool` | the same for a PSS signature, with `algo` for MGF1 too and a salt of `salt_size` bytes; `-1` is the digest's size, which TLS 1.3 requires |

`key.bits()` is the modulus's size and `key.size()` a signature's length in bytes.

`rsa.PrivateKey(der)` is a private key from its PKCS #1 form (the DER of an
`RSA PRIVATE KEY` block, which a PKCS #8 `PRIVATE KEY` holds for RSA). A key
whose modulus isn't the product of its primes, or whose exponents don't fit it,
is an error.

| Function | Gives |
|---|---|
| `key.sign_pkcs1(algo: Algo, message: bytes) -> bytes` | the PKCS #1 v1.5 signature, the same each time |
| `key.sign_pss(algo: Algo, message: bytes) -> bytes` | the PSS signature, with MGF1 of `algo` and a random salt of the digest's size |
| `key.public` | the `PublicKey` |

Signing works by the Chinese remainder theorem, with exponentiations that look
at the secret exponents 4 bits at a time and pick each multiplier by masks from
all 16, so they take the same steps for every key. Each signature is checked
with the public key before it is given out, since a fault in one of the two
halves would otherwise give the key away. A 2048-bit signature takes about
3.7 ms, and a 3072-bit one 11 ms (OpenSSL's, 0.4 and 1.2 ms).

## ECDSA signatures: `crypto/ecdsa`

ECDSA (FIPS 186-5) on the curves `ecdsa.Curve.P256` and `.P384`.

| Function | Gives |
|---|---|
| `PublicKey(curve: Curve, point: bytes) -> PublicKey or Error` | the key whose point is `point`, uncompressed (`0x04`, then x and y); a point not on the curve is an error |
| `key.verify(algo: Algo, message: bytes, signature: bytes) -> bool` | whether `signature`, DER as X.509 and TLS carry it, is the key's signature of `message` hashed with `algo` |
| `key.verify_rs(algo: Algo, message: bytes, r: bytes, s: bytes) -> bool` | the same with `r` and `s` given as big-endian numbers |

`key.point()` gives the point back, uncompressed.

`ecdsa.PrivateKey(curve, scalar:)` is a private key from its scalar, big-endian
and the curve's size (32 or 48 bytes), above 0 and below the curve's order:

| Function | Gives |
|---|---|
| `key.public_key() -> PublicKey` | its public key |
| `key.sign(algo: Algo, message: bytes) -> bytes` | the DER signature of `message` hashed with `algo` |
| `key.sign_rs(algo: Algo, message: bytes) -> (bytes, bytes)` | r and s, each the curve's size |

The nonce is RFC 6979's, made from the key and the message, so the same
message always gets the same signature and no random number can be bad
enough to give the key away. Signing does the same steps whatever the key and
nonce are: the multiplication by the nonce adds one precomputed multiple of
the generator for every 4 bits, picked by looking at all 16 and keeping one by
masks, with formulas that have no special cases (Renes, Costello and Batina,
2016). It takes about 0.25 ms on P-256 and 1 ms on P-384, after a table
that the first signature on a curve makes (about 2 ms on P-256).

A signature must be strict DER: a length in long form, an integer with a 0 byte
it doesn't need, a negative one, or bytes after the end is refused, so that a
signature has one encoding.

Both modules are checked against Wycheproof's test vectors, which aim at the
mistakes signature checks are known for. Checking takes about 0.11 ms for an
RSA signature of 2048 bits and 0.24 ms for 3072, 0.6 ms for P-256 and 3 ms
for P-384.

## Certificates: `crypto/x509`

`x509.parse(der)` reads an X.509 certificate (RFC 5280), and `x509.verify`
checks the chain a server sent:

<!-- kod:
import "io"
let text = must io.read_file("stdlib/crypto/testdata/github_chain.pem")
let now = 1795651200
-->
```kod
import "crypto/x509"

let chain = [must x509.parse(d) for d in must x509.pem_certificates(text)]
let path = x509.verify(chain, host: "github.com", roots: must x509.system_roots(), now: now)
```

`chain` is the server's certificates in the order TLS sends them, its own
first; `now` is seconds since 1970. `verify` gives the path it found, from the
server's certificate up to the root, or an error that says what is wrong. It
checks that:

- every certificate on the path is valid at `now`, and signed by the next one's
  key, with RSA (PKCS #1 v1.5) or ECDSA on P-256 or P-384 and SHA-2;
- each certificate above the server's is a CA (basicConstraints), may sign
  certificates (keyUsage, if it has one), allows as many CAs below it as there
  are (pathLenConstraint), and allows a server (extKeyUsage, if it has one);
- the server's certificate names `host` in its subjectAltName, as a DNS name
  (ignoring case and a trailing dot; `*.example.com` stands for one label, so
  it matches `www.example.com` but not `example.com` or `a.b.example.com`) or,
  for an IPv4 address, as an IP address; the common name isn't used, as browsers
  don't;
- the server's certificate allows a server and a signature;
- no certificate sent has a critical extension this module doesn't know (such
  as name constraints), which RFC 5280 says to refuse.

The certificates may come in any order after the first, with extra ones; it
tries each that could be next. A root is trusted as it is, so only its validity
and signature over the certificate below it count. Revocation isn't checked.

`system_roots()` reads the operating system's trusted roots once: on macOS
those in `/System/Library/Keychains/SystemRootCertificates.keychain`, which
`keychain_certificates(data)` takes out of the keychain file as DER (the
`/etc/ssl/cert.pem` there has fewer), and elsewhere the usual PEM bundles.
`load_roots(path)` reads another PEM file; a certificate in it that can't be read
(an unusual key, say) is left out. A `Certificate` has its fields as read
(`dns_names`, `not_after`, `is_ca`, `key`, ...) and `common_name()` for
messages. `crypto/der` is the DER reader underneath.

## Random bytes: `crypto/random`

`random.secure_bytes(n)` gives `n` bytes from the operating system's
cryptographic generator (`getentropy`), for keys and nonces.
