# Business logic lives here — routers stay thin (parse request, call a
# service, return response), services own the actual rules (e.g. the
# trust-weighted vote threshold check, the outbox-write-in-same-transaction
# pattern). Empty scaffolding for now — populated as endpoint issues (#7,
# #8, #12, #13, #14) land; out of scope for #6 itself.
