# Third-party notices

Market Analysis Audit Lab is licensed under Apache License 2.0, but third-party components retain their own licenses. This file is an attribution index, not a replacement for the license text distributed with each component.

## Bundled project assets

| Component | Use | License / notice |
|---|---|---|
| Contributor Covenant 2.1 | Basis for `CODE_OF_CONDUCT.md` and its Persian translation | CC BY 4.0; © Contributor Covenant contributors |
| Developer Certificate of Origin 1.1 | `DCO` contribution sign-off | Verbatim-copy permission in the DCO file; © The Linux Foundation and contributors |
| Vazirmatn, when present | Persian web/PDF typography | SIL Open Font License 1.1; preserve the font's `OFL.txt` and copyright notice |

The synthetic demo is original project fixture material distributed under the project license. It represents no real identity, channel, content, price series, or market event.

## Runtime dependencies

The application installs third-party Python packages and system libraries through the dependency lock and container build. Typical direct dependencies include FastAPI, Uvicorn, Pydantic, Jinja, pandas, OpenAI's Python library, yt-dlp, yfinance, JSON Schema tooling, Rich, and PDF/font-support packages. Transitive dependencies are not exhaustively reproduced in this hand-maintained file.

Every tagged release must include a machine-generated SBOM and dependency-license inventory based on the exact resolved build. The release process must fail when a required license text is missing, a license is incompatible with distribution, or an asset lacks documented provenance. The installed package metadata and upstream source are authoritative for their license terms.

## External services and data

The following are integrations, not project-owned assets:

- OpenAI APIs and models;
- YouTube pages, APIs, metadata, captions, video, audio, thumbnails, names, and brand features;
- Binance archives and API data;
- Yahoo-origin data accessed through the unofficial `yfinance` client;
- operator-supplied CSV, provider feeds, logos, fonts, transcripts, media, and reports.

The Apache License 2.0 for this repository does not license those services or materials. Operators must follow their current terms, attribution, privacy, access, and redistribution requirements.

## No implied endorsement

Third-party names and trademarks are used only to identify interoperability. Their inclusion does not imply sponsorship, affiliation, certification, or endorsement of this project or any audit result.

To report a missing or incorrect notice, open a documentation issue without attaching proprietary material.
