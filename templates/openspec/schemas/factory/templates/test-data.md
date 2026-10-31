# System Test Data: <!-- Change name -->

<!-- Synthetic only. No production data, no real personal data, no secrets. -->
<!-- Every set is a file under system-tests/data/; this document says what each holds and how it is loaded. -->

## Loading

- `Load:` <!-- the profile's test_data.load with this epic's data directory last, e.g. `python -m scripts.testdata load --env staging openspec/changes/<epic>-<slug>/system-tests/data` — or "built by the loader task (Task <n>, #<issue>)" when the repo has no loader yet -->
- `Unload:` <!-- the profile's test_data.unload, same argument -->

### DS-1: <!-- Name -->

- `Used by:` <!-- ST ids -->
- `Records:` `system-tests/data/DS-1.json` <!-- the file holding the records; one file per set -->
- `Setup:` <!-- the Load command above, plus any step a tester does by hand on top (sign in as a seeded user, …) -->
- `Teardown:` <!-- the Unload command above -->
