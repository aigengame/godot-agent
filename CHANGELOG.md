# Changelog

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
