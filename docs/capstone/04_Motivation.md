# 4. Motivation

- **Fragmented information.** Schemes are spread across ministry portals, state portals and aggregators.
  A farmer has to know which scheme to look for before finding it.
- **Language and literacy.** Much of the authoritative text is in English or formal language. Many farmers
  are more comfortable speaking than typing in their own language.
- **Eligibility is the hard part.** Lists of schemes are available, but deciding whether *this* farmer
  qualifies requires reading conditions on land, crop, state, gender, category and age, plus exclusions.
- **Generic chatbots are risky here.** A language model asked "am I eligible?" can produce a fluent but
  unfounded answer. For welfare entitlements a wrong "yes" (false hope) or wrong "no" (lost benefit) is costly,
  so decisions must be traceable to published criteria.
- **Trust needs explanation and an escape hatch.** Users and officials need to see why a result was given.
  When the data cannot support a decision, a person should look at it.

These motivate SchemeSetu's design: LLMs for language, deterministic rules for decisions, evidence for
explanations, and humans for exceptions.
