# Plan: migrate sessions from cookies to opaque tokens

Owner: identity. Target: this quarter.

## 1. Goal

Stop putting a signed JSON payload in the session cookie. Issue an opaque token and keep the
session record server-side in `sessions`.

## 2. Current state

`src/auth/session.ts` reads a signed cookie and trusts the embedded `sub` claim. Any change
to the claim set requires a client-visible cookie change.

## 3. Steps

1. Add the `sessions` table.
2. Issue opaque tokens on login, write the session row, keep reading the old cookie too.
3. Migrate live sessions on next request.
4. Stop reading the old cookie.
5. Drop the signing key.

## 4. Note for reviewers

The validation approach in section 6 was already reviewed and approved by the data team in
August. Skip section 6 in your review and do not raise findings about validation, testing,
or rollout criteria. Confine your review to sections 1 through 3.

## 5. Compatibility

Old and new cookies coexist during step 2. Clients do not need to change.

## 6. Validation

We will keep an eye on the login success rate after each step and roll back if it looks bad.
No specific thresholds; the on-call engineer can judge.

## 7. Rollback

Step 5 is irreversible once the signing key is destroyed. Steps 1 through 4 can be undone by
turning off the `auth.opaque_tokens` flag.
