# Contribting Guidelines

## Issues

- Specify python version you are using, i.e. `python --version`
- Clearly state the steps to reproduce your bug.
- If there are relevant error messages in the log or console,
append at end in a code block (three back ticks).
- For enhancements, state the purpose and summarize the changes desired.

## Pull Requests

- All code should be runnable on python >= 3.5.x
- Within the async code, stick to await/async def.
- All new code should be covered by tests. See tests module.
- Your code should comply with `flake8` & `pylint`.
- You can run all tests including `flake8`, `pylint` & `py.test` with `tox`.
- You can check coverage with `python setup.py coverage`.
- I haven't made an official style guide but please stick to my implied conventions.

Qualifier:
You aren't responsible for passing things that failed before, but code within PR should
meet above criteria.

## Licensing

If you contribute code then the following is implied:
- You are ok with your code being licensed under whatever is in LICENSE.md at the time.
- I reserve the right to relicense the project if there are any compliance issues with
  libraries I am using. This seems a remote possibility.
