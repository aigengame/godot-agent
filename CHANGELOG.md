# Changelog

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
