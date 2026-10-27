import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beforeRankingPayload, questionnairePayload, QUESTION_LABELS, studyPresentation } from "../src/features/session/studyInstrument.js";
import { requestStudySession, requestStudyCurrent, requestTestQuestionnaire } from "../src/api/sigraApi.js";

const before = { scenario_id: "A", familiarity: "low", priorities: ["efficiency"], presentation_acknowledged: true };

test("instrumento registra antes do ranking sem user_id nem alteração de pesos", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({}) }; };
  await requestStudySession(beforeRankingPayload(before), { fetchImpl });
  await requestStudyCurrent({ fetchImpl });
  assert.match(calls[0].url, /\/study-sessions$/);
  assert.deepEqual(JSON.parse(calls[0].options.body), before);
  assert.equal(calls[0].options.headers["X-SIGRA-CSRF"], "1");
  assert.equal(calls[0].options.credentials, "include");
  assert.doesNotMatch(calls[1].url, /user_id|token/);
});

test("quatro questões separadas não são média nem nota geral", async () => {
  const answers = Object.fromEntries(Object.keys(QUESTION_LABELS).map((key, i) => [key, String(i + 1)]));
  const payload = questionnairePayload(answers, "Fictício");
  assert.deepEqual(Object.values(payload).slice(1), [1, 2, 3, 4]);
  assert.equal(Object.hasOwn(payload, "rating"), false);
  await requestTestQuestionnaire("run 1", payload, { fetchImpl: async (url, options) => {
    assert.match(url, /run%201\/questionnaire$/); assert.equal(options.method, "PATCH");
    assert.deepEqual(JSON.parse(options.body), payload);
    return { ok: true, json: async () => ({}) };
  } });
});

test("faltantes, bools, valores fora da escala e mais de três prioridades são rejeitados", () => {
  const valid = Object.fromEntries(Object.keys(QUESTION_LABELS).map((key) => [key, "4"]));
  for (const value of [undefined, true, "0", "6", "4.1"]) {
    assert.throws(() => questionnairePayload({ ...valid, interface_clarity: value }, ""));
  }
  for (const change of [{ scenario_id: "F" }, { familiarity: "" }, { priorities: ["safety", "safety"] }, { priorities: ["a", "b", "c", "d"] }, { presentation_acknowledged: false }]) {
    assert.throws(() => beforeRankingPayload({ ...before, ...change }));
  }
});

test("telas preservam o formulário, marcam homologação e não inventam consentimento", () => {
  const source = readFileSync(new URL("../src/features/session/StudyBeforeRanking.jsx", import.meta.url), "utf8");
  const presentation = studyPresentation({ mode: "homologation", real_collection_enabled: false });
  assert.match(presentation.heading, /somente participantes fictícios/);
  assert.match(presentation.acknowledgement, /não substitui consentimento/);
  assert.match(source, /presentation\.heading/);
  assert.match(source, /presentation\.acknowledgement/);
  assert.match(source, /controller\.abort/);
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /<RecommendationForm/);
  assert.match(app, /currentUser && !studyReady/);
});

test("pesquisa exige confirmação explícita do servidor e não muda as escolhas", () => {
  for (const meta of [null, {}, { mode: "research" }, { mode: "homologation", real_collection_enabled: true }]) {
    assert.match(studyPresentation(meta).heading, /participantes fictícios/);
  }
  assert.match(studyPresentation({ mode: "research", real_collection_enabled: true }).heading, /Pesquisa acadêmica/);
  assert.deepEqual(beforeRankingPayload(before), before);
});
