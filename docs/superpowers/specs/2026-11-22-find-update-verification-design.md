# Find: verifying an update's provenance before it runs (design proposal)

Status: proposal, 2026-11-22. Docs only; nothing here is implemented. Answers finding M3 of the security review
of 2026-11-22 (`.superpowers/sdd/security-review-2026-11-22.md`).

## The gap

`nobadfind/update.py` installs an update after one Install click, silently (`/VERYSILENT`). Before it runs the
installer it checks: HTTPS to `api.github.com` / `github.com`, the asset name and URL shape
(`github.com/nobad-studio/find/releases/download/find-vX.Y.Z/NobadFind-Setup-X.Y.Z.exe`), no downgrade, the size
from the API, and the SHA-256 against the release's `.sha256` asset and GitHub's `digest` field (when GitHub sends
one).

Every one of those comes from the same release object. Whoever can publish a release in `nobad-studio/find` (a
leaked maintainer token, a leaked CI token with `contents: write`, a compromised release workflow) controls the
installer, its `.sha256` and therefore its `digest`. TLS and the URL pin stop a network attacker; they don't stop
a release publisher. `find-release.yml` already makes a Sigstore build-provenance attestation
(`actions/attest-build-provenance`), but the app never checks it. The installer isn't Authenticode-signed yet.

What we want: the app runs an installer only if it can prove, offline from data it already trusts, that the
installer was built by **our** release workflow from **our** repository at the **tag of that version**, or was
signed by a key only the maintainer holds.

## Options

### A. Verify the GitHub / Sigstore attestation bundle in the app

The release job already produces an in-toto build-provenance statement for the installer's SHA-256, signed with a
short-lived Fulcio certificate whose identity is the workflow
(`https://github.com/nobad-studio/find/.github/workflows/find-release.yml@refs/tags/find-vX.Y.Z`) and logged in
Rekor. Publish the bundle as a release asset (`NobadFind-Setup-X.Y.Z.exe.sigstore.json`; `gh attestation download`
gives the same bundle), then in the app:

1. Download the bundle with the installer (same URL pin, size cap of a few hundred KB).
2. Verify the bundle offline: the certificate chains to the Sigstore public-good root (pinned in the app as a
   trusted-root JSON, updated with app releases), the Rekor inclusion proof / signed entry timestamp is valid and
   inside the certificate's validity, the DSSE signature over the statement verifies with the certificate key.
3. Check the identity: SAN = the exact workflow path above, OIDC issuer
   `https://token.actions.githubusercontent.com`, extensions: source repository `nobad-studio/find` (and its
   numeric repository id, so a re-created repo with the same name fails), source ref `refs/tags/find-vX.Y.Z` for
   the version being installed, `github-hosted` runner.
4. Check the statement: subject name `NobadFind-Setup-X.Y.Z.exe`, subject digest = the SHA-256 we computed from
   the file on disk, predicate type SLSA provenance v1.

- Pros: no new secrets for the maintainer to guard; uses what CI already makes; ties the installer to the source
  tag and the workflow file, so a leaked token alone can't publish an installer that passes (it would also need to
  run our workflow at a tag, which the tag ruleset limits to the owner).
- Cons: the most code. Python has `sigstore` (sigstore-python), but it pulls in a large dependency tree
  (`cryptography`, `pyOpenSSL`, `rfc8785`, `securesystemslib`/TUF, `requests`...) and by default fetches the trust
  root online with TUF; we would pin a version, ship a trusted root, and call its offline verification only. Or
  write a minimal verifier with `cryptography` only (X.509 chain, ECDSA P-256/P-384, DSSE PAE, Rekor SET); smaller
  but security-critical code we own. The Sigstore root rotates (rarely); an app too old to know the new root can't
  verify and must fall back to "download it yourself" (never to running unverified).
- Residual risk: a compromised workflow file at a tag (needs push to a protected tag) or GitHub's OIDC issuer
  itself.

### B. A release-signing key pinned in the app (minisign / Ed25519)

The maintainer holds an Ed25519 key offline (a hardware key or an air-gapped machine). For each release they sign
`NobadFind-Setup-X.Y.Z.exe.sha256` (or the installer) and upload `...minisig`. The app pins one or two public keys
(current + next, for rotation) and verifies the signature over the hash it computed before running anything.

- Pros: tiny and easy to audit (a short pure-Python Ed25519 verifier, or `cryptography`, which the app doesn't
  ship today: `requirements-lock.txt` has no `cryptography`, so it would be a new pinned dependency); fully
  offline; independent of GitHub: a GitHub compromise alone can't pass it.
- Cons: a manual step at every release, by the one person who holds the key (CI must not hold it, or a CI
  compromise is back to today). Key loss means a rotation release signed with the old key; key theft means
  shipping a new pinned key and telling users to update by hand. Breaks the "releases are built by CI from the
  tag" flow a little: CI builds, the maintainer signs, CI (or the maintainer) uploads the signature.

### C. Authenticode, once the installer is code-signed

When a code-signing certificate exists (OV/EV, or Azure Trusted Signing), sign `NobadFind-Setup-*.exe` in the
release job and check it before running: `WinVerifyTrust` (WINTRUST_ACTION_GENERIC_VERIFY_V2, revocation on the
whole chain), then the signer's certificate subject / publisher equals the pinned "NOBAD Studio" name, and
ideally the leaf's or the issuing CA's key is pinned too (subject names alone can be bought).

- Pros: Windows does the crypto; SmartScreen stops warning users; the same check protects manual downloads.
- Cons: costs money and an identity check; the signing key then lives in CI or a cloud HSM, so a CI compromise can
  sign (less independent than B); revocation checks need the network (the update check already has it). Not
  available today.

### D. Minimum hardening now (not a fix)

Require GitHub's `digest` to be present and equal (today an asset without one is checked against the `.sha256`
file alone), and refuse a release whose assets were uploaded by an account other than the release workflow's bot
(`uploader.login == "github-actions[bot]"`). Cheap, but it only raises the bar: both fields still come from the
GitHub API that the attacker in this model controls.

## Recommendation

1. **Now (small, in 1.1.x):** D. Make `digest` mandatory and check the uploader. Say in Settings > Updates exactly
   what is checked.
2. **Next (the real fix):** A, verifying the build-provenance attestation offline against the pinned identity
   (repository + id, workflow path, tag of the version, GitHub-hosted runner) with a pinned Sigstore trusted root.
   It needs no new secret and it matches how releases are already made (CI from an owner-only tag, attested). Ship
   the bundle as a release asset so the app needs no extra host. Prefer a minimal verifier (on a newly pinned `cryptography`) over
   the full sigstore-python stack, with test vectors from real bundles of our own releases (good, wrong workflow,
   wrong tag, wrong repo id, tampered statement, expired certificate without a timestamp, wrong root). If the
   bundle is missing or fails: no install, a plain message ("This update couldn't be verified; it wasn't
   installed. You can download it from GitHub yourself.") and nothing is retried silently.
3. **Later:** C as an additional, independent check when the installer gets code-signed. Keep B in reserve if we
   ever want a check that doesn't depend on GitHub at all; it costs a manual step per release, so only with a
   maintainer decision.

AGENTS.md's update rule changes when 2. lands: "run only when its size and SHA-256 match the release's .sha256
file and GitHub's digest, and its build-provenance attestation verifies against nobad-studio/find's release
workflow at that version's tag".

## Tests the implementation will need

- Recorded bundles from two real releases, verified offline with the pinned root (no network in tests).
- Each identity field wrong in turn (repository, repository id, workflow path, ref, issuer, runner), the subject
  digest off by one byte, a statement for another file name, a bundle from another repository's release: all
  refused, and the installer is never started (the existing fake `start`).
- A missing bundle and an unparsable one: refused with the plain message.
- The pinned trusted root is the file in the source tree (hash checked in a test), never fetched at run time.
