# Changelog

## [0.1.46](https://github.com/aigengame/godot-agent/compare/v0.1.45...v0.1.46) (2026-06-27)


### Features

* **project:** add `gda project list` to enumerate ProjectSettings keys ([#312](https://github.com/aigengame/godot-agent/issues/312)) ([#313](https://github.com/aigengame/godot-agent/issues/313)) ([75a0476](https://github.com/aigengame/godot-agent/commit/75a0476f4bacc839b77440266f99ad210e47334e))

## [0.1.45](https://github.com/aigengame/godot-agent/compare/v0.1.44...v0.1.45) (2026-06-26)


### Features

* a shipped build never carries the gda harness ([#297](https://github.com/aigengame/godot-agent/issues/297)) ([d0c0bac](https://github.com/aigengame/godot-agent/commit/d0c0bac358a381a75c8bcb33297096f6e6ed9ae1))

## [0.1.44](https://github.com/aigengame/godot-agent/compare/v0.1.43...v0.1.44) (2026-06-25)


### Bug Fixes

* **skill:** sync SKILL.md live-ops tables to the surface, add a drift gate ([#294](https://github.com/aigengame/godot-agent/issues/294)) ([cdaf8c2](https://github.com/aigengame/godot-agent/commit/cdaf8c258eb19c3aafdb2d9ee1aadf43d73126c3))

## [0.1.43](https://github.com/aigengame/godot-agent/compare/v0.1.42...v0.1.43) (2026-06-25)


### Features

* **skill:** install into a known agent's skills dir via --provider/--scope ([#292](https://github.com/aigengame/godot-agent/issues/292)) ([04421ce](https://github.com/aigengame/godot-agent/commit/04421ce88635700081e6155319965bb6742fe9b4))

## [0.1.42](https://github.com/aigengame/godot-agent/compare/v0.1.41...v0.1.42) (2026-06-25)


### Features

* **logger:** gda_log() opt-in rich record protocol ([#288](https://github.com/aigengame/godot-agent/issues/288)) ([14293da](https://github.com/aigengame/godot-agent/commit/14293da088bc48af2f18c460e7e60676fca61dd5))

## [0.1.41](https://github.com/aigengame/godot-agent/compare/v0.1.40...v0.1.41) (2026-06-25)


### Features

* **daemon:** run a chosen scene via daemon start --scene ([#285](https://github.com/aigengame/godot-agent/issues/285)) ([b24191d](https://github.com/aigengame/godot-agent/commit/b24191d0282891e0e663b368ec44a5bf8c98c979))
* **diag:** error callstacks in diag errors ([#286](https://github.com/aigengame/godot-agent/issues/286)) ([ae0c41c](https://github.com/aigengame/godot-agent/commit/ae0c41ce434db7eb7e5b354f4b89f889c235e9a0))

## [0.1.40](https://github.com/aigengame/godot-agent/compare/v0.1.39...v0.1.40) (2026-06-25)


### Features

* **logger:** structured runtime log channel via gda logger tail ([#284](https://github.com/aigengame/godot-agent/issues/284)) ([64226e9](https://github.com/aigengame/godot-agent/commit/64226e9b1c4ed69931ff5b4bbe88bf97b503d8bf))

## [0.1.39](https://github.com/aigengame/godot-agent/compare/v0.1.38...v0.1.39) (2026-06-24)


### Bug Fixes

* restructure README & package metadata around the user's fastest path ([#276](https://github.com/aigengame/godot-agent/issues/276)) ([a029da7](https://github.com/aigengame/godot-agent/commit/a029da72b1c2bce10c9e7e7c02e6e219547089c6))

## [0.1.38](https://github.com/aigengame/godot-agent/compare/v0.1.37...v0.1.38) (2026-06-24)


### Bug Fixes

* correct the exit-code ABI table (missing exit 6) + reframe positioning ([#274](https://github.com/aigengame/godot-agent/issues/274)) ([79003a1](https://github.com/aigengame/godot-agent/commit/79003a16147a479c4fa48a8a67d83dbc4b312f28))

## [0.1.37](https://github.com/aigengame/godot-agent/compare/v0.1.36...v0.1.37) (2026-06-24)


### Features

* add the gda skill command and bundled SKILL.md ([#270](https://github.com/aigengame/godot-agent/issues/270)) ([17b380c](https://github.com/aigengame/godot-agent/commit/17b380c6736be2bc24a4f5619a5dab06685e24d9))

## [0.1.36](https://github.com/aigengame/godot-agent/compare/v0.1.35...v0.1.36) (2026-06-23)


### Bug Fixes

* correct outdated README and refresh package description ([#262](https://github.com/aigengame/godot-agent/issues/262)) ([2fb7d0d](https://github.com/aigengame/godot-agent/commit/2fb7d0d20b57eba329ec13d47591f4bf6d509d22))

## [0.1.35](https://github.com/aigengame/godot-agent/compare/v0.1.34...v0.1.35) (2026-06-23)


### Features

* **daemon:** report running daemon's windowed mode via `daemon status` ([#251](https://github.com/aigengame/godot-agent/issues/251)) ([#255](https://github.com/aigengame/godot-agent/issues/255)) ([73e15ab](https://github.com/aigengame/godot-agent/commit/73e15abaad9dec1a7fb44fb9a38d471af41d0950))

## [0.1.34](https://github.com/aigengame/godot-agent/compare/v0.1.33...v0.1.34) (2026-06-23)


### Features

* gda harness lifecycle — version self-sync and paired uninstall ([#225](https://github.com/aigengame/godot-agent/issues/225)) ([#247](https://github.com/aigengame/godot-agent/issues/247)) ([967b679](https://github.com/aigengame/godot-agent/commit/967b679946b396f613af2228f808d7f08ed75db6))
* screen — runtime viewport capture of the running game ([#222](https://github.com/aigengame/godot-agent/issues/222)) ([#248](https://github.com/aigengame/godot-agent/issues/248)) ([4c7eab3](https://github.com/aigengame/godot-agent/commit/4c7eab38fab817ff84c3712582042aa585cd2c35))
* surface live-stack constraints in --schema ([#233](https://github.com/aigengame/godot-agent/issues/233)) ([#245](https://github.com/aigengame/godot-agent/issues/245)) ([430f9f6](https://github.com/aigengame/godot-agent/commit/430f9f67da4f477fc8185105de6c934b72eb0253))

## [0.1.33](https://github.com/aigengame/godot-agent/compare/v0.1.32...v0.1.33) (2026-06-22)


### Features

* input — runtime input simulation into the running game ([#221](https://github.com/aigengame/godot-agent/issues/221)) ([#242](https://github.com/aigengame/godot-agent/issues/242)) ([13fcd91](https://github.com/aigengame/godot-agent/commit/13fcd91cd82d606eb7bfd12a84c9cb9f82fec60c))

## [0.1.32](https://github.com/aigengame/godot-agent/compare/v0.1.31...v0.1.32) (2026-06-22)


### Features

* diag — runtime diagnostics via a daemon-owned per-session log ([#224](https://github.com/aigengame/godot-agent/issues/224)) ([#240](https://github.com/aigengame/godot-agent/issues/240)) ([a773fc4](https://github.com/aigengame/godot-agent/commit/a773fc4b6df91ddcbbc6e57deb1d8862075ecb0d))

## [0.1.31](https://github.com/aigengame/godot-agent/compare/v0.1.30...v0.1.31) (2026-06-22)


### Features

* perf — runtime performance monitoring + the time-windowed live base ([#223](https://github.com/aigengame/godot-agent/issues/223)) ([#239](https://github.com/aigengame/godot-agent/issues/239)) ([385ecb8](https://github.com/aigengame/godot-agent/commit/385ecb8a1ba8ffee03da1f9ce5fbcb057c6ab799))

## [0.1.30](https://github.com/aigengame/godot-agent/compare/v0.1.29...v0.1.30) (2026-06-22)


### Features

* game get/set — live runtime node property get/set ([#220](https://github.com/aigengame/godot-agent/issues/220)) ([#237](https://github.com/aigengame/godot-agent/issues/237)) ([bdee34f](https://github.com/aigengame/godot-agent/commit/bdee34f79d8bfb81368bf8323355615d32755d74))

## [0.1.29](https://github.com/aigengame/godot-agent/compare/v0.1.28...v0.1.29) (2026-06-22)


### Features

* atomic headless writes with file_changed_externally guard ([#226](https://github.com/aigengame/godot-agent/issues/226)) ([#234](https://github.com/aigengame/godot-agent/issues/234)) ([86bc504](https://github.com/aigengame/godot-agent/commit/86bc50482d7f46b4389b4ed9d73209e078271434))

## [0.1.28](https://github.com/aigengame/godot-agent/compare/v0.1.27...v0.1.28) (2026-06-22)


### Features

* surface execution kind in --schema ([#230](https://github.com/aigengame/godot-agent/issues/230)) ([#232](https://github.com/aigengame/godot-agent/issues/232)) ([b2b0ea8](https://github.com/aigengame/godot-agent/commit/b2b0ea865f973d0240ee1ca8f188b51298e11d7d))

## [0.1.27](https://github.com/aigengame/godot-agent/compare/v0.1.26...v0.1.27) (2026-06-21)


### Features

* gda-daemon bootstrap — Phase-2 live operations end-to-end ([#7](https://github.com/aigengame/godot-agent/issues/7)) ([#229](https://github.com/aigengame/godot-agent/issues/229)) ([578f39c](https://github.com/aigengame/godot-agent/commit/578f39c909290333f92d49658b5c0380325eb351))

## [0.1.26](https://github.com/aigengame/godot-agent/compare/v0.1.25...v0.1.26) (2026-06-20)


### Features

* **gda-mcp:** follow active project on roots/list_changed ([#209](https://github.com/aigengame/godot-agent/issues/209)) ([#217](https://github.com/aigengame/godot-agent/issues/217)) ([f5e3093](https://github.com/aigengame/godot-agent/commit/f5e3093f04c591736cafba213d716f4d25cecc54))

## [0.1.25](https://github.com/aigengame/godot-agent/compare/v0.1.24...v0.1.25) (2026-06-20)


### Bug Fixes

* **readme:** render the title image on PyPI via an absolute URL ([#215](https://github.com/aigengame/godot-agent/issues/215)) ([773e446](https://github.com/aigengame/godot-agent/commit/773e4461f1fee70dc9f7cd0b04066e65e651adee))

## [0.1.24](https://github.com/aigengame/godot-agent/compare/v0.1.23...v0.1.24) (2026-06-20)


### Features

* **packaging:** render README on PyPI and add project metadata ([#212](https://github.com/aigengame/godot-agent/issues/212)) ([3dfc2ff](https://github.com/aigengame/godot-agent/commit/3dfc2ff18c08be2378a24a5e8df93228af1d5fd7))

## [0.1.23](https://github.com/aigengame/godot-agent/compare/v0.1.22...v0.1.23) (2026-06-19)


### Features

* **gda-mcp:** project-context resolution via portable precedence ([#194](https://github.com/aigengame/godot-agent/issues/194)) ([#205](https://github.com/aigengame/godot-agent/issues/205)) ([6058dc4](https://github.com/aigengame/godot-agent/commit/6058dc435e414c586d3ffab295bfbdd9e1dc8425))

## [0.1.22](https://github.com/aigengame/godot-agent/compare/v0.1.21...v0.1.22) (2026-06-19)


### Features

* **gda-mcp:** generated stdio MCP server over the gda CLI ([#193](https://github.com/aigengame/godot-agent/issues/193)) ([#203](https://github.com/aigengame/godot-agent/issues/203)) ([14de65d](https://github.com/aigengame/godot-agent/commit/14de65dd576d4c485feaf0a2feb6fdd98459bc48))

## [0.1.21](https://github.com/aigengame/godot-agent/compare/v0.1.20...v0.1.21) (2026-06-18)


### Features

* **gda:** uniform --params-json structured params-input + normalization parity ([#201](https://github.com/aigengame/godot-agent/issues/201)) ([65ed2e6](https://github.com/aigengame/godot-agent/commit/65ed2e6b43f5243285049f7f6794e98a265d8b62))

## [0.1.20](https://github.com/aigengame/godot-agent/compare/v0.1.19...v0.1.20) (2026-06-17)


### Features

* **gda:** add aggregate-schema meta command (whole-surface dump) ([#196](https://github.com/aigengame/godot-agent/issues/196)) ([6e1c8f4](https://github.com/aigengame/godot-agent/commit/6e1c8f42a100affe0bcc8931e290dfd74e92fcb8))

## [0.1.19](https://github.com/aigengame/godot-agent/compare/v0.1.18...v0.1.19) (2026-06-16)


### Features

* **export:** run — add --mode + --output overrides ([#170](https://github.com/aigengame/godot-agent/issues/170)) ([#174](https://github.com/aigengame/godot-agent/issues/174)) ([ad3b2b5](https://github.com/aigengame/godot-agent/commit/ad3b2b5fbf8a2dcc07e2a5f69406442b3c283882))


### Bug Fixes

* **script:** preserve sibling scripts on re-pack in unimported projects ([#164](https://github.com/aigengame/godot-agent/issues/164)) ([#176](https://github.com/aigengame/godot-agent/issues/176)) ([677bf43](https://github.com/aigengame/godot-agent/commit/677bf438f22a9929e8ec6391d80df7d17309b285))

## [0.1.18](https://github.com/aigengame/godot-agent/compare/v0.1.17...v0.1.18) (2026-06-16)


### Bug Fixes

* **runner:** map launch failures + non-UTF-8 output to structured errors ([#33](https://github.com/aigengame/godot-agent/issues/33)) ([#172](https://github.com/aigengame/godot-agent/issues/172)) ([537d451](https://github.com/aigengame/godot-agent/commit/537d451786cb33e8ef5ff9f4574f8ea21312ea99))

## [0.1.17](https://github.com/aigengame/godot-agent/compare/v0.1.16...v0.1.17) (2026-06-16)


### Features

* **export:** run — export a preset via the headless CLI ([#121](https://github.com/aigengame/godot-agent/issues/121)) ([#169](https://github.com/aigengame/godot-agent/issues/169)) ([9a73c73](https://github.com/aigengame/godot-agent/commit/9a73c737b98951d5ba484daa5721248ddd2c6718))
* **project:** add-autoload + remove-autoload — manage singleton autoloads ([#119](https://github.com/aigengame/godot-agent/issues/119)) ([#167](https://github.com/aigengame/godot-agent/issues/167)) ([0e257b0](https://github.com/aigengame/godot-agent/commit/0e257b006a168f25f54c40014efa3c4bc43ccae2))
* **resource:** set + delete — round out resource-file CRUD ([#120](https://github.com/aigengame/godot-agent/issues/120)) ([#168](https://github.com/aigengame/godot-agent/issues/168)) ([5a506ff](https://github.com/aigengame/godot-agent/commit/5a506ff752f3b7bf8b6c6fac50e5996583c221d7))

## [0.1.16](https://github.com/aigengame/godot-agent/compare/v0.1.15...v0.1.16) (2026-06-16)


### Features

* **asset-file:** shader create/get/set + theme create — headless asset-file authoring ([#115](https://github.com/aigengame/godot-agent/issues/115)) ([#161](https://github.com/aigengame/godot-agent/issues/161)) ([a5e7a57](https://github.com/aigengame/godot-agent/commit/a5e7a57df223da27be59063701f6bc1f4e997050))
* **project:** info + get + set — read/write project.godot headlessly ([#111](https://github.com/aigengame/godot-agent/issues/111)) ([#160](https://github.com/aigengame/godot-agent/issues/160)) ([e528d19](https://github.com/aigengame/godot-agent/commit/e528d193dd3a9cd11a2d88dd01b21d8f4433c5e3))
* **project:** static-analysis reads — find-references, dependencies, find-unused-resources, statistics ([#116](https://github.com/aigengame/godot-agent/issues/116)) ([#163](https://github.com/aigengame/godot-agent/issues/163)) ([0fa395f](https://github.com/aigengame/godot-agent/commit/0fa395fccbaff8a5dd3ae22e69988106d96dee56))

## [0.1.15](https://github.com/aigengame/godot-agent/compare/v0.1.14...v0.1.15) (2026-06-16)


### Features

* **export:** list + get — read-only export-preset discovery ([#114](https://github.com/aigengame/godot-agent/issues/114)) ([#159](https://github.com/aigengame/godot-agent/issues/159)) ([5dbcfd5](https://github.com/aigengame/godot-agent/commit/5dbcfd5e3baaacc1b36390d8032d0ad34848c9af))
* **resource:** create + get — establish the .tres resource tracer ([#112](https://github.com/aigengame/godot-agent/issues/112)) ([#157](https://github.com/aigengame/godot-agent/issues/157)) ([d3a6057](https://github.com/aigengame/godot-agent/commit/d3a6057ddbb636fc7637290c17a694c3cf53dd99))
* **resource:** uid — resolve UID ↔ resource path (both directions) ([#113](https://github.com/aigengame/godot-agent/issues/113)) ([#162](https://github.com/aigengame/godot-agent/issues/162)) ([772fc0c](https://github.com/aigengame/godot-agent/commit/772fc0c7af574d29a77634d03925aa411af7c173))
* **scene:** get-exports — list a scene's nodes' [@export](https://github.com/export) properties ([#58](https://github.com/aigengame/godot-agent/issues/58)) ([#158](https://github.com/aigengame/godot-agent/issues/158)) ([f0bcf57](https://github.com/aigengame/godot-agent/commit/f0bcf5752b459f62f70da05d2f4197d3ee2672da))


### Bug Fixes

* **classify:** distinguish deep scene trees from contract violations ([#156](https://github.com/aigengame/godot-agent/issues/156)) ([fea7d72](https://github.com/aigengame/godot-agent/commit/fea7d7213c44f02b3b2473eacba08e40e6ea2669))

## [0.1.14](https://github.com/aigengame/godot-agent/compare/v0.1.13...v0.1.14) (2026-06-15)


### Features

* **node:** connect-signal + disconnect-signal — wire signals to methods ([#57](https://github.com/aigengame/godot-agent/issues/57)) ([#150](https://github.com/aigengame/godot-agent/issues/150)) ([32b8504](https://github.com/aigengame/godot-agent/commit/32b8504b5d8534ed5041b6fdd1bec92718065a60))

## [0.1.13](https://github.com/aigengame/godot-agent/compare/v0.1.12...v0.1.13) (2026-06-15)


### Features

* **script:** attach overwrites-and-reports the displaced script ([#132](https://github.com/aigengame/godot-agent/issues/132)) ([#149](https://github.com/aigengame/godot-agent/issues/149)) ([1b81b46](https://github.com/aigengame/godot-agent/commit/1b81b461922c76c24a10676a8340ea7d09e50493))

## [0.1.12](https://github.com/aigengame/godot-agent/compare/v0.1.11...v0.1.12) (2026-06-15)


### Bug Fixes

* **script:** validate at the script's real res:// path ([#131](https://github.com/aigengame/godot-agent/issues/131)) ([#146](https://github.com/aigengame/godot-agent/issues/146)) ([037ba3d](https://github.com/aigengame/godot-agent/commit/037ba3d57a1fda1196b35e4ffc63139cf3a4ccc3))

## [0.1.11](https://github.com/aigengame/godot-agent/compare/v0.1.10...v0.1.11) (2026-06-15)


### Bug Fixes

* **script:** attach distinguishes type incompatibility from compile failure ([#136](https://github.com/aigengame/godot-agent/issues/136)) ([#137](https://github.com/aigengame/godot-agent/issues/137)) ([169d7a5](https://github.com/aigengame/godot-agent/commit/169d7a55df9395a47326a94ddcff88ee0ba5de20))

## [0.1.10](https://github.com/aigengame/godot-agent/compare/v0.1.9...v0.1.10) (2026-06-15)


### Features

* **script:** script set + script validate + script attach — edit, compile-check, bind ([#118](https://github.com/aigengame/godot-agent/issues/118)) ([#129](https://github.com/aigengame/godot-agent/issues/129)) ([aa60a5b](https://github.com/aigengame/godot-agent/commit/aa60a5bc5586ced92bfdc3694bb5014ff3448e96))

## [0.1.9](https://github.com/aigengame/godot-agent/compare/v0.1.8...v0.1.9) (2026-06-13)


### Features

* **script:** script list + script delete — round out script-file CRUD ([#117](https://github.com/aigengame/godot-agent/issues/117)) ([#127](https://github.com/aigengame/godot-agent/issues/127)) ([56926a3](https://github.com/aigengame/godot-agent/commit/56926a38002e97397519f2427ae579ea9006accc))

## [0.1.8](https://github.com/aigengame/godot-agent/compare/v0.1.7...v0.1.8) (2026-06-13)


### Features

* **script:** script create + script get — script-group tracer ([#110](https://github.com/aigengame/godot-agent/issues/110)) ([#123](https://github.com/aigengame/godot-agent/issues/123)) ([24cd5c5](https://github.com/aigengame/godot-agent/commit/24cd5c5e6427ea27c59bf4dc0915d1584913ef5b))

## [0.1.7](https://github.com/aigengame/godot-agent/compare/v0.1.6...v0.1.7) (2026-06-13)


### Features

* **node:** node get + node set — node property read/write ([#55](https://github.com/aigengame/godot-agent/issues/55)) ([#108](https://github.com/aigengame/godot-agent/issues/108)) ([ddb0135](https://github.com/aigengame/godot-agent/commit/ddb013583fb4bf880a62d385c86e2a94b57644ba))

## [0.1.6](https://github.com/aigengame/godot-agent/compare/v0.1.5...v0.1.6) (2026-06-13)


### Features

* **schema:** emit a uniform error envelope in --schema ([#43](https://github.com/aigengame/godot-agent/issues/43)) ([#104](https://github.com/aigengame/godot-agent/issues/104)) ([015d72c](https://github.com/aigengame/godot-agent/commit/015d72c6e051e629b8cd8b5852e96f613a73c0b8))

## [0.1.5](https://github.com/aigengame/godot-agent/compare/v0.1.4...v0.1.5) (2026-06-13)


### Bug Fixes

* **release:** single-authority version model — retire escape hatch, keep uv.lock in lockstep ([#98](https://github.com/aigengame/godot-agent/issues/98)) ([4e6aa7f](https://github.com/aigengame/godot-agent/commit/4e6aa7fea046a4d3dd2fcddb707bcc236342b0e4))

## [0.1.4](https://github.com/aigengame/godot-agent/compare/v0.1.3...v0.1.4) (2026-06-13)


### Bug Fixes

* **release:** build release artifacts from the tagged commit, not push HEAD ([#91](https://github.com/aigengame/godot-agent/issues/91)) ([11e4030](https://github.com/aigengame/godot-agent/commit/11e40301f3158be596eefa72f1dea54ea681ba8b))
* **release:** gate release-PR maintenance on the manifest version's tag ([#89](https://github.com/aigengame/godot-agent/issues/89)) ([2bb801b](https://github.com/aigengame/godot-agent/commit/2bb801b57b5ae9d9d3917fbdf50ae81c7de438bb))
* **release:** isolate workflow_dispatch from the push concurrency lane ([#93](https://github.com/aigengame/godot-agent/issues/93)) ([7799357](https://github.com/aigengame/godot-agent/commit/77993578686cfac6574b190eb9f33f032a1c0293))
* **release:** make the release publish idempotent with --clobber ([#92](https://github.com/aigengame/godot-agent/issues/92)) ([41cfcc8](https://github.com/aigengame/godot-agent/commit/41cfcc8cb132bcf0062ea0df89ed3aa0423176b6))


### Documentation

* **adr:** document wedged-draft recovery and the residual failure state ([#96](https://github.com/aigengame/godot-agent/issues/96)) ([8a750b8](https://github.com/aigengame/godot-agent/commit/8a750b82eac52841559e426a114f5e17e03a6eb7))

## [0.1.3](https://github.com/aigengame/godot-agent/compare/v0.1.2...v0.1.3) (2026-06-12)

Spurious release produced by the release-automation draft-tag race
([#79](https://github.com/aigengame/godot-agent/issues/79)); no changes over
0.1.2 beyond release plumbing. Kept as-is per the fix-forward decision.

## [0.1.2](https://github.com/aigengame/godot-agent/compare/v0.1.1...v0.1.2) (2026-06-12)

Spurious release produced by the same race
([#79](https://github.com/aigengame/godot-agent/issues/79)); identical to
0.1.1 plus documentation. Kept as-is per the fix-forward decision.

## [0.1.1](https://github.com/aigengame/godot-agent/compare/v0.1.0...v0.1.1) (2026-06-12)


### Features

* **cli:** add root version option ([6490d6c](https://github.com/aigengame/godot-agent/commit/6490d6ca10d3a7add84297a450e9fe1a918fae41))
* **cli:** add root version option ([959bead](https://github.com/aigengame/godot-agent/commit/959bead163ab42d5913369e0d0ab8a8b0e51baf5)), closes [#48](https://github.com/aigengame/godot-agent/issues/48)
* **node:** add gda node add + node list, the node-group tracer ([e294ca2](https://github.com/aigengame/godot-agent/commit/e294ca23fa55e8ea5f398d8b29250edeed3b3394)), closes [#53](https://github.com/aigengame/godot-agent/issues/53)
* **node:** collapse --parent strictness into a canonical-segment rule ([5fc3591](https://github.com/aigengame/godot-agent/commit/5fc359138a155431c619c9197f514f33c35c47d4)), closes [#66](https://github.com/aigengame/godot-agent/issues/66)
* **node:** enforce canonical parent paths in node add ([c484f2d](https://github.com/aigengame/godot-agent/commit/c484f2d0597bd12258a44f140d41cc88010d890d))
* **node:** gda node add + node list — the node-group tracer ([42679ea](https://github.com/aigengame/godot-agent/commit/42679eac6f515de666bf583a4856beed253d95aa))
* **node:** reject '..' segments in node add --parent ([c76aa55](https://github.com/aigengame/godot-agent/commit/c76aa556c2ce15234926ad4bdd8dfacc065fda3c)), closes [#66](https://github.com/aigengame/godot-agent/issues/66)
* **node:** reject empty segments in node add --parent ([51aab71](https://github.com/aigengame/godot-agent/commit/51aab713b3462c31f9650d4bece5fedea7380919)), closes [#66](https://github.com/aigengame/godot-agent/issues/66)
* **node:** reject redundant '.' segments in node add --parent ([0447f5f](https://github.com/aigengame/godot-agent/commit/0447f5fd068c11b45d2ace15f32ae92d26f7fd70)), closes [#66](https://github.com/aigengame/godot-agent/issues/66)
* **scene:** add scene create/get commands with shared --schema emission ([f1262bf](https://github.com/aigengame/godot-agent/commit/f1262bf8af86a134a666b7824ec266dfd0329304)), closes [#18](https://github.com/aigengame/godot-agent/issues/18)
* **scene:** add scene list + scene delete to round out scene-file CRUD ([#71](https://github.com/aigengame/godot-agent/issues/71)) ([b60504d](https://github.com/aigengame/godot-agent/commit/b60504df2116b6215fb481c3f6cb7f75d941b273))
* **scene:** implement headless scene ops with structured failure codes ([a401f3a](https://github.com/aigengame/godot-agent/commit/a401f3a3c7447805b60219838d19a784d462af93)), closes [#18](https://github.com/aigengame/godot-agent/issues/18)
* **scene:** run domain commands against an explicit project context ([d69575c](https://github.com/aigengame/godot-agent/commit/d69575c48532910b7cc302d76aa682e35a3f2013)), closes [#32](https://github.com/aigengame/godot-agent/issues/32) [#18](https://github.com/aigengame/godot-agent/issues/18)


### Bug Fixes

* **cli:** make --schema yield to --help, reject malformed argv, and bind a bool ([a2da6bc](https://github.com/aigengame/godot-agent/commit/a2da6bc926f9d1b462643dddee1a1dd3213f7e29))
* **cli:** make --schema yield to --help, reject malformed argv, and bind a bool ([d8a65de](https://github.com/aigengame/godot-agent/commit/d8a65de76e6a86a9af897ff05239836345685c82)), closes [#36](https://github.com/aigengame/godot-agent/issues/36)
* **errors:** classify environment failures by typed launch_failure, not exit code ([e1b4add](https://github.com/aigengame/godot-agent/commit/e1b4add5fc2fd20cb540fc938dfc6c85b2a8026f))
* **errors:** classify environment failures by typed launch_failure, not exit code ([54a0dd7](https://github.com/aigengame/godot-agent/commit/54a0dd7a00f6be84ffe03fdb8806bca0343a0449)), closes [#15](https://github.com/aigengame/godot-agent/issues/15)
* **gda:** report operation errors via sentinel envelopes ([33de1e9](https://github.com/aigengame/godot-agent/commit/33de1e9087cbbee2f6868d0c0ac99a344294d1b2)), closes [#38](https://github.com/aigengame/godot-agent/issues/38)
* **node:** refuse node add when a declared node class degrades on load ([7d99a50](https://github.com/aigengame/godot-agent/commit/7d99a50a7e678a2dc5b702930ca782b980ee03ff)), closes [#64](https://github.com/aigengame/godot-agent/issues/64)
* **node:** refuse node add when instanced sub-scenes vanish on load ([a78e321](https://github.com/aigengame/godot-agent/commit/a78e32186a77004f2170fb4cf1e592ba3cdf218d))
* **node:** refuse node add when instanced sub-scenes vanish on load ([b53a673](https://github.com/aigengame/godot-agent/commit/b53a673b8b82160dd4523167f281a9641f2c86f1)), closes [#64](https://github.com/aigengame/godot-agent/issues/64)
* **node:** refuse node add when the scene instantiates to null ([3e8da77](https://github.com/aigengame/godot-agent/commit/3e8da77bf4c08e2beec8270def4a8318e138fb87)), closes [#64](https://github.com/aigengame/godot-agent/issues/64)
* **node:** report a broken registered class_name as uninstantiable_script ([6331e1a](https://github.com/aigengame/godot-agent/commit/6331e1a84216fa6e93bb2ac433fd87d99f2ae420))
* **node:** report a broken registered class_name as uninstantiable_script ([4d10811](https://github.com/aigengame/godot-agent/commit/4d10811f8d2d0363cc506849ff4356a80d2bd22a)), closes [#65](https://github.com/aigengame/godot-agent/issues/65)
* **ops:** guarantee a single clean process exit for every dispatch ([91933ed](https://github.com/aigengame/godot-agent/commit/91933ed76b77395ef35508662375d3bfe75fc479)), closes [#31](https://github.com/aigengame/godot-agent/issues/31) [#18](https://github.com/aigengame/godot-agent/issues/18)
* **parser:** take the last end sentinel so payload content can't truncate the result ([80cb857](https://github.com/aigengame/godot-agent/commit/80cb857d279679b88f32b7bada88b9ad75ec19a5))
* **parser:** take the last end sentinel so payload content can't truncate the result ([5503a3f](https://github.com/aigengame/godot-agent/commit/5503a3f58daf4506dafb204ec8a24c6439ac2095)), closes [#34](https://github.com/aigengame/godot-agent/issues/34)
* **scene:** harden scene create integrity ([3b0ea9b](https://github.com/aigengame/godot-agent/commit/3b0ea9b09278b036d5d3f20326101428cfc70e0c))
* **scene:** harden scene create integrity ([b051939](https://github.com/aigengame/godot-agent/commit/b051939e21de6862fa19336b8ed07f327fa439c0)), closes [#35](https://github.com/aigengame/godot-agent/issues/35)
* **scene:** read scene state without executing scene code ([83d76f9](https://github.com/aigengame/godot-agent/commit/83d76f9e102be7104838557db9dde82da2a5b415)), closes [#30](https://github.com/aigengame/godot-agent/issues/30) [#18](https://github.com/aigengame/godot-agent/issues/18)


### Documentation

* **catalog:** annotate scene/node slices with their issue refs ([33dd8ec](https://github.com/aigengame/godot-agent/commit/33dd8ec47419eeee74b5b4e489e632b0db406ee8))
* **catalog:** annotate scene/node slices with their issue refs ([7bcbfd5](https://github.com/aigengame/godot-agent/commit/7bcbfd57ca63150af155b8543b86218b1678d947))
* **catalog:** cover degraded node classes in the integrity boundary ([80675cf](https://github.com/aigengame/godot-agent/commit/80675cf505652211658b663a8ed6e10e9ca6b58b)), closes [#64](https://github.com/aigengame/godot-agent/issues/64)
* **catalog:** document node add type resolution and uninstantiable_script ([3e94bdf](https://github.com/aigengame/godot-agent/commit/3e94bdfded0792e983304e674fa537014631a8ee)), closes [#65](https://github.com/aigengame/godot-agent/issues/65)
* **catalog:** document strict canonical node-path addressing ([14a25e4](https://github.com/aigengame/godot-agent/commit/14a25e4a36b1cf4567ea566620be3fff4b3ff253)), closes [#66](https://github.com/aigengame/godot-agent/issues/66)
* **catalog:** document the node-mutation integrity boundary ([1b93663](https://github.com/aigengame/godot-agent/commit/1b93663db2caf66b57192bf4972b53180eea8f8e)), closes [#64](https://github.com/aigengame/godot-agent/issues/64)
* **catalog:** mark node add/list shipped and document node-path addressing ([2b67bb0](https://github.com/aigengame/godot-agent/commit/2b67bb03df6e7aa94cda95dee9b585770103e5a4))
* fix rfind cross-references in ADR-0002 and the security test docstring ([b451f48](https://github.com/aigengame/godot-agent/commit/b451f48a2e082f0339925b9a4d81ee261c23f51c)), closes [#34](https://github.com/aigengame/godot-agent/issues/34)
* mark scene create/get shipped and document the round-trip ([31ea506](https://github.com/aigengame/godot-agent/commit/31ea506688461617c15b1c53903e2dc34ca3d5af)), closes [#18](https://github.com/aigengame/godot-agent/issues/18)
* **readme:** add workflow badges ([13df10a](https://github.com/aigengame/godot-agent/commit/13df10ac633f1834adde3db71d756e46cc24593b)), closes [#28](https://github.com/aigengame/godot-agent/issues/28)
* **readme:** keep project status at capability level, defer detail to the catalog ([195402d](https://github.com/aigengame/godot-agent/commit/195402d4bfd6fdb2f2e662d243441a10579da585))
* **readme:** state the bare-vs---json output convention for all commands ([2542535](https://github.com/aigengame/godot-agent/commit/2542535c165d5b9a2660ff5ecf8274dda76346bf)), closes [#18](https://github.com/aigengame/godot-agent/issues/18)
