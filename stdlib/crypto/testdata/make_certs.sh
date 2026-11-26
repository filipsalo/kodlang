#!/bin/sh
# Makes the certificates x509_test.kod checks, with OpenSSL 3.4 or later
# (for -not_before and -not_after): run from this directory. They are
# checked in, so this runs only to change them. Every certificate is valid
# from 2025 to 2035 unless its name says otherwise; the test's "now" is
# 2026-06-01. leaf.key.pem and leaf_sha512.key.pem are the keys of leaf.pem
# and leaf_sha512.pem: test keys, for nothing else.
set -e
OPENSSL=${OPENSSL:-openssl}
FROM=20250101000000Z
TO=20350101000000Z
cd "$(dirname "$0")"
# Everything but github.com's chain, which was fetched, not made.
find . -name '*.pem' ! -name github_chain.pem ! -name usertrust_ecc_root.pem -delete
rm -f *.key *.csr *.ext *.srl

key() {
    case $2 in
        rsa) $OPENSSL genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out $1.key 2>/dev/null ;;
        p256) $OPENSSL genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out $1.key ;;
        p384) $OPENSSL genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-384 -out $1.key ;;
    esac
}

# root NAME KIND
root() {
    key $1 $2
    printf 'basicConstraints=critical,CA:true\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n' > $1.ext
    $OPENSSL req -new -key $1.key -subj "/O=Kod tests/CN=$1" -out $1.csr
    $OPENSSL x509 -req -in $1.csr -key $1.key -extfile $1.ext -not_before $FROM -not_after $TO -sha384 -out $1.pem
}

# cert NAME KIND ISSUER HASH FROM TO EXTENSIONS...
cert() {
    name=$1 kind=$2 issuer=$3 hash=$4 from=$5 to=$6
    shift 6
    key $name $kind
    : > $name.ext
    for e in "$@"; do
        printf '%s\n' "$e" >> $name.ext
    done
    $OPENSSL req -new -key $name.key -subj "/O=Kod tests/CN=$name" -out $name.csr
    $OPENSSL x509 -req -in $name.csr -CA $issuer.pem -CAkey $issuer.key -set_serial 0x$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n') -extfile $name.ext -not_before $from -not_after $to -$hash -out $name.pem
}

LEAF_EXT='keyUsage=critical,digitalSignature'
SERVER='extendedKeyUsage=serverAuth'
CA_EXT='basicConstraints=critical,CA:true'
SIGN='keyUsage=critical,keyCertSign,cRLSign'

root root_rsa rsa
root root_ec p384
cert inter p256 root_rsa sha256 $FROM $TO "$CA_EXT,pathlen:0" "$SIGN" "$SERVER"
cert leaf p256 inter sha256 $FROM $TO "subjectAltName=DNS:example.test,DNS:*.example.test,IP:127.0.0.1" "$LEAF_EXT" "$SERVER"
cert leaf_rsa rsa root_ec sha384 $FROM $TO "subjectAltName=DNS:rsa.example.test" "$LEAF_EXT" "$SERVER"
cert leaf_sha512 p384 root_ec sha512 $FROM $TO "subjectAltName=DNS:big.example.test"
cert expired p256 inter sha256 20200101000000Z 20210101000000Z "subjectAltName=DNS:example.test" "$LEAF_EXT"
cert not_yet p256 inter sha256 20300101000000Z $TO "subjectAltName=DNS:example.test" "$LEAF_EXT"
cert client_only p256 inter sha256 $FROM $TO "subjectAltName=DNS:example.test" "$LEAF_EXT" "extendedKeyUsage=clientAuth"
cert odd_critical p256 inter sha256 $FROM $TO "subjectAltName=DNS:example.test" "$LEAF_EXT" "1.2.3.4=critical,DER:0500"
cert no_sign p256 inter sha256 $FROM $TO "subjectAltName=DNS:example.test" "keyUsage=critical,keyEncipherment"
# A leaf certificate used as an issuer, and a CA below the pathlen:0 one.
cert not_ca p256 inter sha256 $FROM $TO "subjectAltName=DNS:notca.example.test" "$LEAF_EXT"
cert under_not_ca p256 not_ca sha256 $FROM $TO "subjectAltName=DNS:example.test" "$LEAF_EXT"
cert inter2 p256 inter sha256 $FROM $TO "$CA_EXT" "$SIGN"
cert under_inter2 p256 inter2 sha256 $FROM $TO "subjectAltName=DNS:example.test" "$LEAF_EXT"
# The keys of two server certificates stay, for the TLS server's tests.
mv leaf.key leaf.key.pem
mv leaf_sha512.key leaf_sha512.key.pem
rm -f *.key *.csr *.ext *.srl
