/* Independent implementation B: JavaScript Kernel VM and work-list pipeline.
 *
 * This file consumes JSON bytes and imports no prototype code.  It deliberately
 * duplicates canonicalization, hashing, bootstrap, rules, runtime, and comparison.
 */

import crypto from "node:crypto";

const IMPLEMENTATION = "node-independent-b-v1";
const REQUIRED_ADMISSION_REASONS = ["identity_mismatch", "kernel_binding_mismatch", "law_contract", "law_missing", "malformed_artifact", "node_shape_invalid", "resource_exhausted", "unknown_opcode"];
const HOST_POST_ADMISSION_REASONS = ["compile_resource_exhausted", "cross_authority_mismatch", "effect_not_allowed", "operation_projection_mismatch", "parse_invalid", "profile_mismatch", "replay_profile_mismatch", "rng_draw_budget", "runtime_profile_projection_mismatch", "runtime_resource_exhausted", "schedule_backward"];

function ordered(value) {
  if (Array.isArray(value)) return value.map(ordered);
  if (value !== null && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) result[key] = ordered(value[key]);
    return result;
  }
  return value;
}

function canonicalBytes(value) {
  return Buffer.from(JSON.stringify(ordered(value)), "utf8");
}

function contentIdentity(domain, payload) {
  const hash = crypto.createHash("sha256");
  hash.update(Buffer.from(domain, "utf8"));
  hash.update(Buffer.from([0]));
  hash.update(canonicalBytes(payload));
  return `sha256:${hash.digest("hex")}`;
}

function clone(value) {
  return structuredClone(value);
}

class SemanticFailure extends Error {
  constructor(reason, args = {}) {
    super(reason);
    this.reason = reason;
    this.arguments = args;
  }
}

function decimalInteger(value) {
  if (typeof value === "number" && Number.isSafeInteger(value)) return BigInt(value);
  if (typeof value === "string" && /^-?[0-9]+$/.test(value)) return BigInt(value);
  return null;
}

function exactResult(value, left, right) {
  if (typeof left === "string" || typeof right === "string") return value.toString();
  const number = Number(value);
  if (!Number.isSafeInteger(number)) return value.toString();
  return number;
}

function valueMatches(value, kind) {
  const checks = {
    Any: () => true,
    Value: () => true,
    Unit: (item) => item === null,
    Int: (item) => decimalInteger(item) !== null,
    Str: (item) => typeof item === "string",
    Bool: (item) => typeof item === "boolean",
    Record: (item) => item !== null && typeof item === "object" && !Array.isArray(item),
    List: (item) => Array.isArray(item),
  };
  return Boolean(checks[kind] && checks[kind](value));
}

function payloadOf(envelope) {
  if (!envelope || typeof envelope.payload !== "object" || Array.isArray(envelope.payload)) {
    throw new SemanticFailure("malformed_artifact");
  }
  return envelope.payload;
}

class VM {
  constructor(kernel, effectHandler = null) {
    this.kernel = kernel;
    this.effectHandler = effectHandler;
    this.consultedLaws = [];
    this.steps = 0;
  }

  law(lawId, args) {
    const definition = this.kernel.laws[lawId];
    if (!definition) throw new SemanticFailure("law_missing", { law: lawId });
    if (JSON.stringify(Object.keys(args).sort()) !== JSON.stringify(Object.keys(definition.parameters).sort()) || !Object.entries(definition.parameters).every(([name, kind]) => valueMatches(args[name], kind))) {
      throw new SemanticFailure("law_contract", { law: lawId, surface: "parameters" });
    }
    this.consultedLaws.push(lawId);
    const start = this.steps;
    const result = this.evaluate(definition.body, { ...args });
    if (definition.resource_accounting.unit !== "vm_step" || this.steps - start > definition.resource_accounting.maximum) throw new SemanticFailure("law_contract", { law: lawId, surface: "resource_accounting" });
    if (!valueMatches(result, definition.result)) throw new SemanticFailure("law_contract", { law: lawId, surface: "result" });
    return result;
  }

  evaluate(node, environment) {
    this.steps += 1;
    if (this.steps > this.kernel.limits.max_vm_steps) {
      throw new SemanticFailure("resource_exhausted", { resource: "vm_steps" });
    }
    if (!node || typeof node !== "object" || Array.isArray(node)) {
      throw new SemanticFailure("node_shape_invalid");
    }
    const operation = node.op;
    if (operation === "literal") return clone(node.value);
    if (operation === "var") {
      if (!Object.hasOwn(environment, node.name)) throw new SemanticFailure("node_shape_invalid", { binding: node.name });
      return environment[node.name];
    }
    if (operation === "get") {
      let current = this.evaluate(node.value, environment);
      for (const part of node.path) current = current[part];
      return clone(current);
    }
    if (operation === "object") {
      const result = {};
      for (const key of Object.keys(node.fields).sort()) result[key] = this.evaluate(node.fields[key], environment);
      return result;
    }
    if (operation === "list") return node.items.map((item) => this.evaluate(item, environment));
    if (operation === "sequence") {
      let result = null;
      for (const item of node.items) result = this.evaluate(item, environment);
      return result;
    }
    if (operation === "let") {
      const nested = { ...environment };
      nested[node.name] = this.evaluate(node.value, environment);
      return this.evaluate(node.then, nested);
    }
    if (operation === "if") {
      const branch = this.evaluate(node.condition, environment) ? node.then : node.else;
      return this.evaluate(branch, environment);
    }
    if (operation === "require") {
      if (!this.evaluate(node.condition, environment)) {
        const args = {};
        for (const key of Object.keys(node.arguments || {}).sort()) args[key] = this.evaluate(node.arguments[key], environment);
        throw new SemanticFailure(node.reason, args);
      }
      return null;
    }
    if (operation === "eq") {
      return JSON.stringify(ordered(this.evaluate(node.left, environment))) === JSON.stringify(ordered(this.evaluate(node.right, environment)));
    }
    if (operation === "not") return !this.evaluate(node.value, environment);
    if (operation === "and") {
      for (const item of node.items) if (!this.evaluate(item, environment)) return false;
      return true;
    }
    if (operation === "or") {
      for (const item of node.items) if (this.evaluate(item, environment)) return true;
      return false;
    }
    if (["lt", "le", "ge", "add", "sub", "mod", "bit_xor", "bit_and", "shift_left", "shift_right"].includes(operation)) {
      const leftRaw = this.evaluate(node.left, environment);
      const rightRaw = this.evaluate(node.right, environment);
      const left = decimalInteger(leftRaw);
      const right = decimalInteger(rightRaw);
      if (left === null || right === null) throw new SemanticFailure("node_shape_invalid", { operand: "not-integer" });
      if (operation === "lt") return left < right;
      if (operation === "le") return left <= right;
      if (operation === "ge") return left >= right;
      if (operation === "add") return exactResult(left + right, leftRaw, rightRaw);
      if (operation === "sub") return exactResult(left - right, leftRaw, rightRaw);
      if (operation === "mod") return exactResult(left % right, leftRaw, rightRaw);
      if (operation === "bit_xor") return exactResult(left ^ right, leftRaw, rightRaw);
      if (operation === "bit_and") return exactResult(left & right, leftRaw, rightRaw);
      if (operation === "shift_left") return exactResult(left << right, leftRaw, rightRaw);
      return exactResult(left >> right, leftRaw, rightRaw);
    }
    if (operation === "concat") return node.items.map((item) => String(this.evaluate(item, environment))).join("");
    if (operation === "to_string") return String(this.evaluate(node.value, environment));
    if (operation === "sha256_u32") {
      const bytes = Buffer.from(String(this.evaluate(node.value, environment)), "utf8");
      return crypto.createHash("sha256").update(bytes).digest().readUInt32BE(0);
    }
    if (operation === "has_key") {
      const mapping = this.evaluate(node.map, environment);
      const key = this.evaluate(node.key, environment);
      return mapping !== null && typeof mapping === "object" && !Array.isArray(mapping) && Object.hasOwn(mapping, key);
    }
    if (operation === "lookup") {
      const mapping = this.evaluate(node.map, environment);
      const key = this.evaluate(node.key, environment);
      if (!mapping || typeof mapping !== "object" || !Object.hasOwn(mapping, key)) throw new SemanticFailure("node_shape_invalid", { lookup: key });
      return clone(mapping[key]);
    }
    if (operation === "keys_equal") {
      const left = this.evaluate(node.left, environment);
      const right = this.evaluate(node.right, environment);
      return JSON.stringify(Object.keys(left).sort()) === JSON.stringify(Object.keys(right).sort());
    }
    if (operation === "type_map_matches") {
      const values = this.evaluate(node.values, environment);
      const signature = this.evaluate(node.signature, environment);
      if (!values || !signature || JSON.stringify(Object.keys(values).sort()) !== JSON.stringify(Object.keys(signature).sort())) return false;
      return Object.entries(signature).every(([name, kind]) => this.kernel.wire_types.includes(kind) && valueMatches(values[name], kind));
    }
    if (operation === "set_equal") {
      const left = [...this.evaluate(node.left, environment)].sort();
      const right = [...this.evaluate(node.right, environment)].sort();
      return JSON.stringify(left) === JSON.stringify(right);
    }
    if (operation === "program_effects") {
      const pending = [this.evaluate(node.program, environment)];
      const effects = new Set();
      while (pending.length) {
        const current = pending.pop();
        if (Array.isArray(current)) pending.push(...current);
        else if (current !== null && typeof current === "object") {
          if (current.op === "effect" && typeof current.kind === "string") effects.add(current.kind);
          if (current.op === "call_kernel") {
            const called = this.kernel.laws[current.law];
            if (!called) throw new SemanticFailure("law_missing", { law: current.law });
            for (const effect of called.effects) effects.add(effect);
          }
          pending.push(...Object.values(current));
        }
      }
      return [...effects].sort();
    }
    if (operation === "evaluate_program") {
      const program = this.evaluate(node.program, environment);
      const nested = this.evaluate(node.environment, environment);
      if (!nested || typeof nested !== "object" || Array.isArray(nested)) throw new SemanticFailure("node_shape_invalid", { environment: "not-record" });
      return this.evaluate(program, nested);
    }
    if (operation === "select_unique") {
      const candidates = this.evaluate(node.candidates, environment);
      const direction = this.evaluate(node.direction, environment);
      if (!Array.isArray(candidates) || !candidates.length) throw new SemanticFailure("rule_none");
      const priorities = candidates.map((candidate) => candidate.priority);
      const extreme = direction === "max" ? Math.max(...priorities) : Math.min(...priorities);
      const selected = candidates.filter((candidate) => candidate.priority === extreme);
      if (selected.length !== 1) throw new SemanticFailure("rule_ambiguous");
      return clone(selected[0].rule);
    }
    if (operation === "lex_gt") {
      const left = this.evaluate(node.left, environment);
      const right = this.evaluate(node.right, environment);
      if (!Array.isArray(left) || !Array.isArray(right)) throw new SemanticFailure("node_shape_invalid", { operand: "not-list" });
      return compareKey(left, right) > 0;
    }
    if (operation === "assoc_path") {
      const result = clone(this.evaluate(node.map, environment));
      const raw = this.evaluate(node.path, environment);
      const path = typeof raw === "string" ? raw.split(".") : [...raw];
      let current = result;
      for (const part of path.slice(0, -1)) {
        if (!Object.hasOwn(current, part)) current[part] = {};
        current = current[part];
      }
      current[path.at(-1)] = this.evaluate(node.value, environment);
      return result;
    }
    if (operation === "call_kernel") {
      const args = {};
      for (const key of Object.keys(node.arguments).sort()) args[key] = this.evaluate(node.arguments[key], environment);
      return this.law(node.law, args);
    }
    if (operation === "effect") {
      if (!this.effectHandler) throw new SemanticFailure("node_shape_invalid", { effect: node.kind });
      const args = {};
      for (const key of Object.keys(node.arguments).sort()) args[key] = this.evaluate(node.arguments[key], environment);
      return this.effectHandler(node.kind, args);
    }
    throw new SemanticFailure("unknown_opcode", { opcode: operation });
  }
}

function kernelDiagnostic(kernel, event, args) {
  const definition = kernel.admission_diagnostics?.[event];
  if (!definition) return { code: "unavailable", stage: "internal", arguments: args, location: { kind: "artifact", value: "$" } };
  return { code: definition.code, stage: definition.stage, arguments: args, location: { kind: "artifact", value: "$" } };
}

function ldbDiagnostic(ldb, reason, args, location) {
  const code = ldb.reason_diagnostics[reason];
  const definition = ldb.diagnostics[code];
  return { code, stage: definition.stage, arguments: args, location };
}

function semanticDiagnostic(kernel, ldb, failure, location) {
  if (Object.hasOwn(kernel.admission_diagnostics || {}, failure.reason)) return kernelDiagnostic(kernel, failure.reason, failure.arguments);
  return ldbDiagnostic(ldb, failure.reason, failure.arguments, location);
}

function programContract(program, kernel = null) {
  const effects = new Set();
  const refusals = new Set();
  const pending = [program];
  while (pending.length) {
    const current = pending.pop();
    if (Array.isArray(current)) pending.push(...current);
    else if (current !== null && typeof current === "object") {
      if (current.op === "effect" && typeof current.kind === "string") effects.add(current.kind);
      if (current.op === "require" && typeof current.reason === "string") refusals.add(current.reason);
      if (current.op === "select_unique") { refusals.add("rule_none"); refusals.add("rule_ambiguous"); }
      if (current.op === "call_kernel" && kernel !== null) {
        const called = kernel.laws[current.law];
        if (!called) throw new SemanticFailure("law_missing", { law: current.law });
        for (const effect of called.effects) effects.add(effect);
        for (const refusal of called.refusals) refusals.add(refusal);
      }
      pending.push(...Object.values(current));
    }
  }
  return [effects, refusals];
}

function validateProgram(kernel, root) {
  const pending = [root];
  let count = 0;
  while (pending.length) {
    const node = pending.pop();
    count += 1;
    if (count > kernel.limits.max_program_nodes) throw new SemanticFailure("resource_exhausted", { resource: "program_nodes" });
    if (!node || typeof node !== "object" || Array.isArray(node) || typeof node.op !== "string") throw new SemanticFailure("node_shape_invalid");
    const schema = kernel.meta_opcodes[node.op];
    if (!schema) throw new SemanticFailure("unknown_opcode", { opcode: node.op });
    if (JSON.stringify(Object.keys(node).sort()) !== JSON.stringify([...schema.fields].sort())) throw new SemanticFailure("node_shape_invalid", { opcode: node.op, fields: Object.keys(node).sort() });
    if (node.op === "call_kernel" && !Object.hasOwn(kernel.laws, node.law)) throw new SemanticFailure("law_missing", { law: node.law });
    if (node.op === "effect" && !Object.hasOwn(kernel.effect_kinds, node.kind)) throw new SemanticFailure("node_shape_invalid", { effect: node.kind });
    const singles = ["value", "then", "else", "condition", "left", "right", "map", "key", "values", "signature", "program", "environment", "candidates", "direction", "path"];
    for (const key of singles) if (node[key] && typeof node[key] === "object" && !Array.isArray(node[key])) pending.push(node[key]);
    if (Array.isArray(node.items)) pending.push(...node.items);
    for (const key of ["fields", "arguments"]) if (node[key] && typeof node[key] === "object" && !Array.isArray(node[key])) pending.push(...Object.values(node[key]));
  }
}

function admit(kernelEnvelope, ldbEnvelope) {
  let kernel;
  try { kernel = payloadOf(kernelEnvelope); }
  catch { return { admitted: false, diagnostic: { code: "unavailable", stage: "ingress" }, implementation: IMPLEMENTATION }; }
  const kernelIdentity = contentIdentity("kernel", kernel);
  if (kernelEnvelope.identity !== kernelIdentity) return { admitted: false, diagnostic: kernelDiagnostic(kernel, "identity_mismatch", { artifact: "kernel" }), implementation: IMPLEMENTATION };
  if (JSON.stringify(Object.keys(kernel.admission_diagnostics || {}).sort()) !== JSON.stringify(REQUIRED_ADMISSION_REASONS)) return { admitted: false, diagnostic: kernelDiagnostic(kernel, "malformed_artifact", { artifact: "kernel.admission_diagnostics" }), implementation: IMPLEMENTATION };
  let ldb;
  try { ldb = payloadOf(ldbEnvelope); }
  catch { return { admitted: false, diagnostic: kernelDiagnostic(kernel, "malformed_artifact", { artifact: "ldb" }), implementation: IMPLEMENTATION }; }
  const ldbIdentity = contentIdentity("ldb", ldb);
  if (ldbEnvelope.identity !== ldbIdentity) return { admitted: false, diagnostic: kernelDiagnostic(kernel, "identity_mismatch", { artifact: "ldb" }), implementation: IMPLEMENTATION };
  if (ldb.kernel_identity !== kernelIdentity) return { admitted: false, diagnostic: kernelDiagnostic(kernel, "kernel_binding_mismatch", {}), implementation: IMPLEMENTATION };
  try {
    const kernelRefusals = new Set();
    for (const law of Object.values(kernel.laws)) {
      validateProgram(kernel, law.body);
      if (JSON.stringify(Object.keys(law).sort()) !== JSON.stringify(["body", "effects", "parameters", "refusals", "resource_accounting", "result"])) throw new SemanticFailure("law_contract", { surface: "shape" });
      if (!kernel.wire_types.includes(law.result) || Object.values(law.parameters).some((kind) => !kernel.wire_types.includes(kind))) throw new SemanticFailure("law_contract", { surface: "types" });
      if (law.resource_accounting.unit !== "vm_step" || !Number.isInteger(law.resource_accounting.maximum) || law.resource_accounting.maximum < 1) throw new SemanticFailure("law_contract", { surface: "resource_accounting" });
      const [effects, refusals] = programContract(law.body, kernel);
      if (JSON.stringify([...effects].sort()) !== JSON.stringify([...law.effects].sort()) || JSON.stringify([...refusals].sort()) !== JSON.stringify([...law.refusals].sort())) throw new SemanticFailure("law_contract", { surface: "effects/refusals" });
      for (const reason of refusals) kernelRefusals.add(reason);
    }
    for (const effect of Object.values(kernel.effect_kinds)) if (!Object.hasOwn(kernel.laws, effect.law)) throw new SemanticFailure("law_missing", { law: effect.law });
    const languageRefusals = new Set();
    for (const rule of ldb.rules) {
      validateProgram(kernel, rule.when); validateProgram(kernel, rule.body);
      const [, whenRefusals] = programContract(rule.when, kernel);
      const [, bodyRefusals] = programContract(rule.body, kernel);
      if ([...whenRefusals, ...bodyRefusals].some((reason) => !Object.hasOwn(ldb.reason_diagnostics, reason))) throw new SemanticFailure("law_contract", { surface: "rule_diagnostic_authority" });
      for (const reason of [...whenRefusals, ...bodyRefusals]) languageRefusals.add(reason);
    }
    for (const operation of Object.values(ldb.operations)) {
      validateProgram(kernel, operation.body);
      if (Object.values(operation.signature).some((kind) => !kernel.wire_types.includes(kind))) throw new SemanticFailure("law_contract", { surface: "operation_signature" });
      const [, refusals] = programContract(operation.body, kernel);
      if ([...refusals].some((reason) => !Object.hasOwn(ldb.reason_diagnostics, reason))) throw new SemanticFailure("law_contract", { surface: "operation_diagnostic_authority" });
      for (const reason of refusals) languageRefusals.add(reason);
    }
    for (const lawId of ldb.required_kernel_laws) if (!Object.hasOwn(kernel.laws, lawId)) throw new SemanticFailure("law_missing", { law: lawId });
    for (const [reason, code] of Object.entries(ldb.reason_diagnostics)) if (!ldb.diagnostics[code] || typeof reason !== "string") throw new SemanticFailure("node_shape_invalid", { diagnostic: code });
    if ([...kernelRefusals].some((reason) => !Object.hasOwn(ldb.reason_diagnostics, reason))) throw new SemanticFailure("law_contract", { surface: "kernel_diagnostic_authority" });
    const reachablePostReasons = new Set([...HOST_POST_ADMISSION_REASONS, ...kernelRefusals, ...languageRefusals]);
    if (JSON.stringify(Object.keys(ldb.reason_diagnostics).sort()) !== JSON.stringify([...reachablePostReasons].sort()) || JSON.stringify([...new Set(Object.values(ldb.reason_diagnostics))].sort()) !== JSON.stringify(Object.keys(ldb.diagnostics).sort())) throw new SemanticFailure("law_contract", { surface: "post_diagnostic_reverse_closure" });
    if (!Object.hasOwn(ldb.runtime_profiles, ldb.default_runtime_profile)) throw new SemanticFailure("law_contract", { surface: "default_runtime_profile" });
    const profile = ldb.runtime_profiles[ldb.default_runtime_profile];
    if (JSON.stringify(Object.keys(profile).sort()) !== JSON.stringify(["allowed_effects", "budgets", "numeric", "phase_order", "rng_mapping"]) || profile.allowed_effects.some((effect) => !Object.hasOwn(kernel.effect_kinds, effect)) || JSON.stringify(Object.keys(profile.budgets).sort()) !== JSON.stringify(["max_draws", "max_events", "max_queue"]) || Object.values(profile.budgets).some((limit) => !Number.isInteger(limit) || limit < 0) || Object.keys(profile.phase_order).length === 0 || Object.values(profile.phase_order).some((rank) => !Number.isInteger(rank))) throw new SemanticFailure("law_contract", { surface: "runtime_profile" });
    for (const packageDefinition of Object.values(ldb.packages)) {
      if (!packageDefinition.operations || typeof packageDefinition.operations !== "object" || Array.isArray(packageDefinition.operations) || Object.entries(packageDefinition.operations).some(([name, selected]) => selected !== true || !Object.hasOwn(ldb.operations, name))) throw new SemanticFailure("law_contract", { surface: "package_operation_closure" });
    }
    const configuredPhases = new Set([ldb.source_package_phase, ldb.source_collection_phase, ...ldb.compiler_pipeline]);
    const rulePhases = new Set(ldb.rules.map((rule) => rule.phase));
    if ([...configuredPhases].some((phase) => !rulePhases.has(phase)) || Object.values(ldb.compiler_artifacts).some((phase) => !ldb.compiler_pipeline.includes(phase))) throw new SemanticFailure("law_contract", { surface: "compiler_pipeline" });
  } catch (error) {
    const failure = error instanceof SemanticFailure ? error : new SemanticFailure("node_shape_invalid");
    const event = Object.hasOwn(kernel.admission_diagnostics, failure.reason) ? failure.reason : "node_shape_invalid";
    return { admitted: false, diagnostic: kernelDiagnostic(kernel, event, failure.arguments), implementation: IMPLEMENTATION };
  }
  const receiptPayload = { artifact_kind: "kernel-ldb-admission", kernel_identity: kernelIdentity, ldb_identity: ldbIdentity, implementation: IMPLEMENTATION, diagnostic_inventory: Object.keys(ldb.diagnostics).sort() };
  return { admitted: true, ...receiptPayload, admission_identity: contentIdentity("admission-receipt", receiptPayload) };
}

function selectRule(vm, ldb, phase, subject, source, sequence) {
  const environment = { authority: ldb, source, subject, sequence };
  const candidates = [];
  for (const rule of ldb.rules) if (vm.law("rule.applicable", { rule, phase, environment })) candidates.push({ priority: vm.law("rule.priority", { rule }), rule });
  let selected;
  try { selected = vm.law("rule.choose", { candidates }); }
  catch (error) {
    if (error instanceof SemanticFailure && !Object.hasOwn(error.arguments, "phase")) error.arguments.phase = phase;
    throw error;
  }
  return [vm.evaluate(selected.body, environment), selected.id];
}

function compileModel(request) {
  const admission = admit(request.kernel, request.ldb);
  if (!admission.admitted) return { status: "refused", diagnostic: admission.diagnostic, implementation: IMPLEMENTATION };
  const peer = request.peer_admission;
  const kernel = payloadOf(request.kernel);
  const ldb = payloadOf(request.ldb);
  const peerFields = ["admission_identity", "admitted", "artifact_kind", "diagnostic_inventory", "implementation", "kernel_identity", "ldb_identity"];
  const peerShapeValid = peer && typeof peer === "object" && !Array.isArray(peer) && JSON.stringify(Object.keys(peer).sort()) === JSON.stringify(peerFields);
  const peerPayload = peerShapeValid ? Object.fromEntries(Object.entries(peer).filter(([key]) => !["admission_identity", "admitted"].includes(key))) : null;
  if (!peerShapeValid || peer.admitted !== true || peer.admission_identity !== contentIdentity("admission-receipt", peerPayload) || peer.artifact_kind !== "kernel-ldb-admission" || peer.kernel_identity !== admission.kernel_identity || peer.ldb_identity !== admission.ldb_identity || JSON.stringify(peer.diagnostic_inventory) !== JSON.stringify(Object.keys(ldb.diagnostics).sort()) || typeof peer.implementation !== "string") return { status: "refused", diagnostic: kernelDiagnostic(kernel, "kernel_binding_mismatch", { artifact: "peer_admission" }), implementation: IMPLEMENTATION };
  const source = request.source;
  const vm = new VM(kernel);
  const consultedRules = [];
  const ast = [];
  const hir = [];
  const lowered = [];
  let packageSelection;
  try {
    let packageRule;
    [packageSelection, packageRule] = selectRule(vm, ldb, ldb.source_package_phase, source, source, -1);
    consultedRules.push(packageRule);
    if (!packageSelection || typeof packageSelection !== "object" || Array.isArray(packageSelection) || JSON.stringify(Object.keys(packageSelection).sort()) !== JSON.stringify(["package", "release"])) throw new SemanticFailure("parse_invalid", { surface: "source_package" });
    const [sourceEvents, collectionRule] = selectRule(vm, ldb, ldb.source_collection_phase, source, source, -1);
    consultedRules.push(collectionRule);
    if (!Array.isArray(sourceEvents)) throw new SemanticFailure("parse_invalid", { surface: "source_collection" });
    let ruleSteps = 2;
    sourceEvents.forEach((sourceEvent, index) => {
      let current = sourceEvent;
      let ruleId;
      const stageOutputs = {};
      for (const phase of ldb.compiler_pipeline) {
        ruleSteps += 1;
        if (ruleSteps > kernel.limits.max_rule_steps) throw new SemanticFailure("compile_resource_exhausted", { resource: "rule_steps" });
        [current, ruleId] = selectRule(vm, ldb, phase, current, source, index);
        consultedRules.push(ruleId); stageOutputs[phase] = clone(current);
      }
      ast.push(stageOutputs[ldb.compiler_artifacts.ast]); hir.push(stageOutputs[ldb.compiler_artifacts.typed_hir]);
      lowered.push(stageOutputs[ldb.compiler_artifacts.rir]);
    });
  } catch (error) {
    const failure = error instanceof SemanticFailure ? error : new SemanticFailure("parse_invalid");
    return { status: "refused", diagnostic: semanticDiagnostic(kernel, ldb, failure, { kind: "source", value: source.artifact_kind || "source" }), consulted_kernel_laws: [...new Set(vm.consultedLaws)].sort(), consulted_ldb_rules: consultedRules, implementation: IMPLEMENTATION };
  }
  const packageDefinition = packageSelection.release;
  const operationTable = {};
  for (const name of Object.keys(packageDefinition.operations)) operationTable[name] = clone(ldb.operations[name]);
  const lockPayload = { artifact_kind: "package-lock", package: source.package, release: packageDefinition };
  const lock = { payload: lockPayload, identity: contentIdentity("lock", lockPayload) };
  const rirPayload = { artifact_kind: "rir-semantic-payload", events: lowered, operation_table: operationTable, package: source.package, runtime_profile_definition: clone(ldb.runtime_profiles[ldb.default_runtime_profile]), diagnostics: clone(ldb.diagnostics), reason_diagnostics: clone(ldb.reason_diagnostics), comparison_policy: clone(ldb.comparison_policy) };
  const rir = { payload: rirPayload, identity: contentIdentity("rir", rirPayload) };
  const resolvedPayload = { artifact_kind: "resolved-model", kernel_identity: admission.kernel_identity, ldb_identity: admission.ldb_identity, lock_identity: lock.identity, rir_identity: rir.identity };
  const resolvedModel = { payload: resolvedPayload, identity: contentIdentity("resolved-model", resolvedPayload) };
  const debugPayload = { artifact_kind: "debug-map", source_identity: contentIdentity("source", source), ast, implementation: IMPLEMENTATION };
  return { status: "compiled", ast, typed_hir: hir, package_lock: lock, rir, resolved_model: resolvedModel, debug_map: { payload: debugPayload, identity: contentIdentity("debug-map", debugPayload) }, consulted_kernel_laws: [...new Set(vm.consultedLaws)].sort(), consulted_ldb_rules: [...new Set(consultedRules)].sort(), implementation: IMPLEMENTATION };
}

function readPath(root, path) {
  let current = root;
  for (const part of path.split(".")) current = current[part];
  return clone(current);
}

function sealRun(payload) {
  return { ...payload, run_identity: contentIdentity("evaluation-run", payload) };
}

function sealComparison({ admission, policy, left, right, leftProfile, rightProfile, experiment, scenario, artifactKind, matches, consultedLaws }) {
  const payload = {
    artifact_kind: artifactKind,
    kernel_identity: admission.kernel_identity,
    ldb_identity: admission.ldb_identity,
    left_run_identity: left.run_identity,
    right_run_identity: right.run_identity,
    left_profile_identity: leftProfile.identity,
    right_profile_identity: rightProfile.identity,
    left_resolved_model_identity: leftProfile.payload.resolved_model_identity,
    right_resolved_model_identity: rightProfile.payload.resolved_model_identity,
    experiment_identity: contentIdentity("experiment", experiment),
    scenario_identity: contentIdentity("scenario", scenario),
    policy_identity: contentIdentity("comparison-policy", policy),
    portable_fields: clone(policy.portable_fields),
    matches,
    consulted_kernel_laws: [...new Set(consultedLaws)].sort(),
    producer: IMPLEMENTATION,
  };
  return { status: "completed", artifact_kind: artifactKind, matches, consulted_kernel_laws: payload.consulted_kernel_laws, payload, identity: contentIdentity("comparison-artifact", payload), implementation: IMPLEMENTATION };
}

function compareKey(left, right) {
  for (let index = 0; index < Math.max(left.length, right.length); index += 1) {
    if (left[index] < right[index]) return -1;
    if (left[index] > right[index]) return 1;
  }
  return 0;
}

function evaluateModel(request) {
  const admission = admit(request.kernel, request.ldb);
  if (!admission.admitted) return { status: "refused", diagnostic: admission.diagnostic, implementation: IMPLEMENTATION };
  const kernel = payloadOf(request.kernel);
  const ldb = payloadOf(request.ldb);
  const rir = request.rir;
  const resolved = request.resolved_model;
  if (!rir.payload || typeof rir.payload !== "object" || Array.isArray(rir.payload) || rir.identity !== contentIdentity("rir", rir.payload)) return { status: "refused", diagnostic: kernelDiagnostic(kernel, "identity_mismatch", { artifact: "rir" }), implementation: IMPLEMENTATION };
  if (!resolved.payload || typeof resolved.payload !== "object" || Array.isArray(resolved.payload) || resolved.identity !== contentIdentity("resolved-model", resolved.payload) || resolved.payload.rir_identity !== rir.identity || resolved.payload.kernel_identity !== admission.kernel_identity || resolved.payload.ldb_identity !== admission.ldb_identity) return { status: "refused", diagnostic: kernelDiagnostic(kernel, "identity_mismatch", { artifact: "resolved_model" }), implementation: IMPLEMENTATION };
  const payload = rir.payload;
  if (!Object.hasOwn(ldb.packages, payload.package)) return { status: "refused", diagnostic: ldbDiagnostic(ldb, "operation_projection_mismatch", { surface: "package" }, { kind: "artifact", value: rir.identity }), implementation: IMPLEMENTATION };
  const packageDefinition = ldb.packages[payload.package];
  const expected = {};
  for (const name of Object.keys(packageDefinition.operations)) expected[name] = ldb.operations[name];
  if (JSON.stringify(ordered(payload.operation_table)) !== JSON.stringify(ordered(expected))) return { status: "refused", diagnostic: ldbDiagnostic(ldb, "operation_projection_mismatch", {}, { kind: "artifact", value: rir.identity }), implementation: IMPLEMENTATION };
  const expectedRuntimeProfile = ldb.runtime_profiles[ldb.default_runtime_profile];
  if (JSON.stringify(ordered(payload.runtime_profile_definition)) !== JSON.stringify(ordered(expectedRuntimeProfile)) || JSON.stringify(ordered(payload.diagnostics)) !== JSON.stringify(ordered(ldb.diagnostics)) || JSON.stringify(ordered(payload.reason_diagnostics)) !== JSON.stringify(ordered(ldb.reason_diagnostics)) || JSON.stringify(ordered(payload.comparison_policy)) !== JSON.stringify(ordered(ldb.comparison_policy))) return { status: "refused", diagnostic: ldbDiagnostic(ldb, "runtime_profile_projection_mismatch", {}, { kind: "artifact", value: rir.identity }), implementation: IMPLEMENTATION };
  const profile = request.resolved_profile;
  if (!profile.payload || typeof profile.payload !== "object" || Array.isArray(profile.payload) || profile.identity !== contentIdentity("resolved-profile", profile.payload)) return { status: "refused", diagnostic: kernelDiagnostic(kernel, "identity_mismatch", { artifact: "resolved_profile" }), implementation: IMPLEMENTATION };
  const profilePayload = profile.payload;
  if (JSON.stringify(Object.keys(profilePayload).sort()) !== JSON.stringify(["artifact_kind", "definition_identity", "evaluator", "kernel_identity", "ldb_identity", "resolved_model_identity"]) || profilePayload.artifact_kind !== "resolved-runtime-profile" || profilePayload.definition_identity !== contentIdentity("runtime-profile-definition", expectedRuntimeProfile) || profilePayload.kernel_identity !== admission.kernel_identity || profilePayload.ldb_identity !== admission.ldb_identity || profilePayload.resolved_model_identity !== resolved.identity || profilePayload.evaluator !== IMPLEMENTATION) return { status: "refused", diagnostic: ldbDiagnostic(ldb, "profile_mismatch", {}, { kind: "artifact", value: profile.identity }), implementation: IMPLEMENTATION };
  const runtimeProfile = expectedRuntimeProfile;
  const scenario = request.scenario;
  const experiment = request.experiment;
  let state = clone(scenario.initial_state);
  let rngStates = {};
  const queue = clone(payload.events);
  let nextSequence = Math.max(-1, ...queue.map((event) => event.sequence)) + 1;
  const trace = [];
  const metrics = [];
  const signals = [];
  const allDraws = [];
  const consulted = [];
  let dispatched = 0;
  while (queue.length) {
    const scheduler = new VM(kernel);
    try { queue.sort((left, right) => compareKey(scheduler.law("scheduler.key", { event: left, phase_order: runtimeProfile.phase_order }), scheduler.law("scheduler.key", { event: right, phase_order: runtimeProfile.phase_order }))); }
    catch (error) {
      if (!(error instanceof SemanticFailure)) throw error;
      return { status: "refused", diagnostic: semanticDiagnostic(kernel, ldb, error, { kind: "artifact", value: rir.identity }), implementation: IMPLEMENTATION };
    }
    consulted.push(...scheduler.consultedLaws);
    const event = queue.shift();
    dispatched += 1;
    const transaction = { snapshot: clone(state), rngAfter: clone(rngStates), writes: {}, metrics: [], signals: [], children: [], draws: [] };
    let eventVm;
    const effectHandler = (kind, args) => {
      if (!runtimeProfile.allowed_effects.includes(kind)) throw new SemanticFailure("effect_not_allowed", { effect: kind });
      const definition = kernel.effect_kinds[kind];
      if (!definition) throw new SemanticFailure("effect_not_allowed", { effect: kind });
      const intent = eventVm.law(definition.law, args);
      const disposition = intent.disposition;
      if (disposition === "read_snapshot") return readPath(transaction.snapshot, intent.path);
      if (disposition === "buffer_write") {
        transaction.writes = eventVm.law("transaction.accept_write", { writes: transaction.writes, path: intent.path, value: intent.value }); return null;
      }
      if (disposition === "sample") {
        if (!eventVm.law("budget.within", { used: allDraws.length + transaction.draws.length + 1, limit: runtimeProfile.budgets.max_draws })) throw new SemanticFailure("rng_draw_budget");
        if (!Object.hasOwn(transaction.rngAfter, intent.stream)) transaction.rngAfter[intent.stream] = eventVm.law("rng.seed_stream", { seed: experiment.seed, stream: intent.stream });
        const result = eventVm.law("rng.bounded", { state: transaction.rngAfter[intent.stream], bound: intent.bound });
        transaction.rngAfter[intent.stream] = result.state;
        transaction.draws.push({ stream: intent.stream, candidate: result.candidate, accepted: result.accepted, value: result.value });
        return result.value;
      }
      if (disposition === "buffer_metric") { transaction.metrics.push({ metric: intent.metric, value: clone(intent.value) }); return null; }
      if (disposition === "buffer_signal") { transaction.signals.push({ signal: intent.signal, value: clone(intent.value) }); return null; }
      if (disposition === "buffer_child") {
        const child = clone(intent.event); child.sequence = nextSequence + transaction.children.length;
        const childKey = eventVm.law("scheduler.key", { event: child, phase_order: runtimeProfile.phase_order });
        const activeKey = eventVm.law("scheduler.key", { event, phase_order: runtimeProfile.phase_order });
        if (!eventVm.law("scheduler.child_allowed", { child_key: childKey, active_key: activeKey })) throw new SemanticFailure("schedule_backward", { event: child.id });
        if (!eventVm.law("budget.within", { used: queue.length + transaction.children.length + 1, limit: runtimeProfile.budgets.max_queue })) throw new SemanticFailure("runtime_resource_exhausted", { resource: "queue" });
        transaction.children.push(child); return null;
      }
      throw new SemanticFailure("effect_not_allowed", { effect: kind });
    };
    eventVm = new VM(kernel, effectHandler);
    try {
      if (!eventVm.law("budget.within", { used: dispatched, limit: runtimeProfile.budgets.max_events })) throw new SemanticFailure("runtime_resource_exhausted", { resource: "events" });
      const operation = payload.operation_table[event.operation];
      eventVm.evaluate(operation.body, { ...event.arguments });
      let nextState = clone(state);
      for (const [path, value] of Object.entries(transaction.writes)) nextState = eventVm.law("transition.apply", { snapshot: nextState, path, value });
      state = nextState;
    } catch (error) {
      const failure = error instanceof SemanticFailure ? error : new SemanticFailure("operation_projection_mismatch");
      consulted.push(...eventVm.consultedLaws);
      const diagnostic = semanticDiagnostic(kernel, ldb, failure, { kind: "event", value: event.id });
      const audit = { artifact_kind: "terminal-audit", committed_trace_prefix: trace, last_committed_snapshot: state, refusing_event: event, discarded: { writes: transaction.writes, rng_draws: transaction.draws, signals: transaction.signals, children: transaction.children }, diagnostic, resolved_profile_identity: profile.identity, resolved_model_identity: resolved.identity };
      return sealRun({ status: "runtime_refusal", final_state: state, metrics, signals, rng_trace: allDraws, trace, diagnostic, terminal_audit: { payload: audit, identity: contentIdentity("terminal-audit", audit) }, resolved_profile_identity: profile.identity, reproduction_identity: [admission.kernel_identity, admission.ldb_identity, resolved.identity, profile.identity, contentIdentity("experiment", experiment), contentIdentity("scenario", scenario)], consulted_kernel_laws: [...new Set(consulted)].sort(), implementation: IMPLEMENTATION });
    }
    rngStates = transaction.rngAfter;
    metrics.push(...transaction.metrics); signals.push(...transaction.signals); allDraws.push(...transaction.draws);
    queue.push(...transaction.children); nextSequence += transaction.children.length;
    trace.push({ event: event.id, state: clone(state), metrics: clone(transaction.metrics), signals: clone(transaction.signals) });
    consulted.push(...eventVm.consultedLaws);
  }
  return sealRun({ status: "completed", final_state: state, metrics, signals, rng_trace: allDraws, trace, diagnostic: null, resolved_profile_identity: profile.identity, reproduction_identity: [admission.kernel_identity, admission.ldb_identity, resolved.identity, profile.identity, contentIdentity("experiment", experiment), contentIdentity("scenario", scenario)], consulted_kernel_laws: [...new Set(consulted)].sort(), implementation: IMPLEMENTATION });
}

function compareRuns(request, cross) {
  const admission = admit(request.kernel, request.ldb);
  if (!admission.admitted) return { status: "refused", diagnostic: admission.diagnostic, implementation: IMPLEMENTATION };
  const kernel = payloadOf(request.kernel);
  const ldb = payloadOf(request.ldb);
  const left = request.left;
  const right = request.right;
  const leftProfile = request.left_profile;
  const rightProfile = request.right_profile;
  const reason = cross ? "cross_authority_mismatch" : "replay_profile_mismatch";
  const expectedDefinitionIdentity = contentIdentity("runtime-profile-definition", ldb.runtime_profiles[ldb.default_runtime_profile]);
  const profileFields = ["artifact_kind", "definition_identity", "evaluator", "kernel_identity", "ldb_identity", "resolved_model_identity"];
  for (const [run, profile] of [[left, leftProfile], [right, rightProfile]]) {
    const runPayload = Object.fromEntries(Object.entries(run).filter(([key]) => key !== "run_identity"));
    if (run.run_identity !== contentIdentity("evaluation-run", runPayload)) return { status: "refused", diagnostic: ldbDiagnostic(ldb, reason, { artifact: "run" }, { kind: "artifact", value: "comparison" }), implementation: IMPLEMENTATION };
    if (!profile.payload || typeof profile.payload !== "object" || Array.isArray(profile.payload) || JSON.stringify(Object.keys(profile.payload).sort()) !== JSON.stringify(profileFields) || profile.identity !== contentIdentity("resolved-profile", profile.payload) || run.resolved_profile_identity !== profile.identity || profile.payload.artifact_kind !== "resolved-runtime-profile" || profile.payload.definition_identity !== expectedDefinitionIdentity || profile.payload.evaluator !== run.implementation) return { status: "refused", diagnostic: ldbDiagnostic(ldb, reason, { artifact: "profile" }, { kind: "artifact", value: "comparison" }), implementation: IMPLEMENTATION };
    const expected = [admission.kernel_identity, admission.ldb_identity, profile.payload.resolved_model_identity, profile.identity, contentIdentity("experiment", request.experiment), contentIdentity("scenario", request.scenario)];
    if (JSON.stringify(run.reproduction_identity) !== JSON.stringify(expected) || profile.payload.kernel_identity !== admission.kernel_identity || profile.payload.ldb_identity !== admission.ldb_identity) return { status: "refused", diagnostic: ldbDiagnostic(ldb, reason, { artifact: "binding" }, { kind: "artifact", value: "comparison" }), implementation: IMPLEMENTATION };
  }
  const policy = ldb.comparison_policy;
  const vm = new VM(kernel);
  if (!cross) {
    let compatible;
    try { compatible = vm.law("comparison.replay_compatible", { left_profile: left.resolved_profile_identity, right_profile: right.resolved_profile_identity }); }
    catch (error) {
      if (!(error instanceof SemanticFailure)) throw error;
      return { status: "refused", diagnostic: semanticDiagnostic(kernel, ldb, error, { kind: "artifact", value: "comparison" }), implementation: IMPLEMENTATION, consulted_kernel_laws: vm.consultedLaws };
    }
    if (!compatible || JSON.stringify(left.reproduction_identity) !== JSON.stringify(right.reproduction_identity)) return { status: "refused", diagnostic: ldbDiagnostic(ldb, "replay_profile_mismatch", {}, { kind: "artifact", value: "comparison" }), implementation: IMPLEMENTATION, consulted_kernel_laws: vm.consultedLaws };
    const matches = policy.portable_fields.every((field) => JSON.stringify(ordered(left[field])) === JSON.stringify(ordered(right[field])));
    return sealComparison({ admission, policy, left, right, leftProfile, rightProfile, experiment: request.experiment, scenario: request.scenario, artifactKind: policy.replay_artifact_kind, matches, consultedLaws: vm.consultedLaws });
  }
  const commonLeft = left.reproduction_identity.filter((_, index) => index !== 3);
  const commonRight = right.reproduction_identity.filter((_, index) => index !== 3);
  if (left.resolved_profile_identity === right.resolved_profile_identity || JSON.stringify(commonLeft) !== JSON.stringify(commonRight)) return { status: "refused", diagnostic: ldbDiagnostic(ldb, "cross_authority_mismatch", {}, { kind: "artifact", value: "comparison" }), implementation: IMPLEMENTATION };
  const matches = policy.portable_fields.every((field) => JSON.stringify(ordered(left[field])) === JSON.stringify(ordered(right[field])));
  return sealComparison({ admission, policy, left, right, leftProfile, rightProfile, experiment: request.experiment, scenario: request.scenario, artifactKind: policy.cross_artifact_kind, matches, consultedLaws: [] });
}

function dispatch(request) {
  if (request.command === "bootstrap") return admit(request.kernel, request.ldb);
  if (request.command === "compile") return compileModel(request);
  if (request.command === "evaluate") return evaluateModel(request);
  if (request.command === "compare_replay") return compareRuns(request, false);
  if (request.command === "compare_cross") return compareRuns(request, true);
  return { status: "internal_error", implementation: IMPLEMENTATION };
}

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
let response;
try { response = dispatch(JSON.parse(raw)); }
catch (error) { response = { status: "internal_error", implementation: IMPLEMENTATION, exception: error.constructor.name, detail: error.message }; }
process.stdout.write(JSON.stringify(ordered(response)));
