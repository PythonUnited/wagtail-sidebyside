# Changelog

## 0.2.0 (2026-11-18)

- New status *Not started* for translations nothing was translated in yet.
- Overview filters: all pages, pages with work, started translations with work.
- README: early release disclaimer, back up database and media first.
- Template tag `{% sidebyside_head %}` (`{% load sidebyside %}`): canonical and
  `hreflang` links; an untranslated copy points its canonical to the source.

## 0.1.3 (2026-11-17)

- Show a warning instead of an empty box when an image file is missing on the server.

## 0.1.2 (2026-11-17)

- Show bullets and numbers of lists in the source column.

## 0.1.1 (2026-11-17)

- Fix the LICENSE link in the README on PyPI.
- Update the GitHub Actions to their Node 24 versions.

## 0.1.0 (2026-11-17)

First release.

- Side-by-side translation screen, tree sync, live preview.
- Machine translation with Claude (optional extra `claude`), pluggable backends.
- Hooks: `sidebyside_block_kind`, `sidebyside_construct_rows`,
  `sidebyside_before_save_translation`, `sidebyside_after_save_translation`.
- `import_localize_drafts` command for moving from wagtail-localize.
