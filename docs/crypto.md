---
icon: lucide/lock
---

# Cryptography

The modules under `stdlib/crypto/` are the pieces TLS 1.3 is built from,
written in Kod: hashes, HMAC and HKDF, two AEAD ciphers, a key exchange and the
operating system's random numbers. Each is checked against the test vectors
of the standard that defines it.

```kod
import "crypto/sha2"
import "crypto/hmac"
import "encoding/hex"

print(hex.encode(sha2.sha256(b"abc")))
// ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad

let tag = hmac.mac(.Sha256, key: b"key", data: b"The quick brown fox")
```

The code that handles secrets (the cipher, the MAC, the key exchange and
`hmac.equal`) does the same work whatever the secret is: it doesn't branch on a
secret or use one to pick an array element. That is how it keeps secrets from
showing in how long it takes. It hasn't been audited.

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

A key of another length panics.

## Random bytes: `crypto/random`

`random.secure_bytes(n)` gives `n` bytes from the operating system's
cryptographic generator (`getentropy`), for keys and nonces.
