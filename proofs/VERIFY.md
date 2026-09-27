# Verification of PREREGISTRATION.md

This file documents the exact commands to verify the timestamp signatures of `PREREGISTRATION.md` using only files present in this repository.

## FreeTSA
```bash
openssl ts -verify -data PREREGISTRATION.md -in PREREGISTRATION.md.freetsa.tsr -CAfile proofs/freetsa_cacert.pem
```
Output should end with: `Verification: OK`

## DigiCert
```bash
openssl ts -verify -data PREREGISTRATION.md -in PREREGISTRATION.md.digicert.tsr -CAfile proofs/digicert_trusted_root_g4.pem -untrusted proofs/digicert_certs.pem
```
Output should end with: `Verification: OK` (A warning about a certificate not being a CA cert is normal).

## OpenTimestamps (OTS)
```bash
ots verify PREREGISTRATION.md.ots
```
Note: Until the Bitcoin blockchain confirms the transaction, this will show "Pending confirmation". Once confirmed, it will show a success message. To upgrade the file before verifying (if it was created recently):
```bash
ots upgrade PREREGISTRATION.md.ots
```
