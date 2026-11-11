# Baseline sources

| Baseline | Library | Commit used to test the harness | Licence |
| --- | --- | --- | --- |
| ML-DSA-44 (FIPS 204) | PQClean crypto_sign/ml-dsa-44/clean | 0586a82 | see PQClean META.yml |
| SLH-DSA-SHA2-128s/128f (FIPS 205) | pq-code-package/slhdsa-c | b8553e8 | see repository LICENSE |
| FN-DSA-512 (draft FIPS 206) | pornin/c-fn-dsa | 1b85888 | see repository LICENSE |
| Ed25519 (RFC 8032) | LoupVaillant/Monocypher | f5f0a19 | see repository LICENCE |
| ECDSA P-256 + SHA-256 | kmackay/micro-ecc | 541b3a7 | see repository LICENSE.txt |

The wrappers in this folder only map each library to the NIST crypto_sign API.
Signed message format: signature || message.
