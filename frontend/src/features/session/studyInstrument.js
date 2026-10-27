export const QUESTION_LABELS = Object.freeze({
  interface_clarity: "A interface foi clara para mim.",
  first_vehicle_explanation: "Entendi por que o primeiro veículo foi recomendado.",
  scenario_coherence: "O resultado parece coerente com o cenário apresentado.",
  influential_criteria: "Consigo identificar os critérios que mais influenciaram a recomendação.",
});

export function studyPresentation(metadata) {
  const research = metadata?.mode === "research" && metadata?.real_collection_enabled === true;
  return research ? {
    heading: "Pesquisa acadêmica — registro antes do resultado",
    notice: "Cenários A–E identificam as tarefas do roteiro aprovado; não substituem as preferências do formulário.",
    acknowledgement: "Li a apresentação da atividade e as orientações do protocolo aprovado.",
  } : {
    heading: "Homologação do instrumento — somente participantes fictícios",
    notice: "Coleta real desativada nesta entrega. Cenários A–E identificam as tarefas do roteiro; não substituem as preferências do formulário.",
    acknowledgement: "Li a apresentação da atividade fictícia. Isto não substitui consentimento acadêmico aprovado.",
  };
}

export function questionnairePayload(answers, comment) {
  const payload = { comment };
  for (const key of Object.keys(QUESTION_LABELS)) {
    if (!/^[1-5]$/.test(String(answers[key] ?? ""))) throw new Error("Responda às quatro questões (1 a 5).");
    payload[key] = Number(answers[key]);
  }
  return payload;
}

export function beforeRankingPayload(form) {
  if (!/^[A-E]$/.test(form.scenario_id) || !["none", "low", "medium", "high"].includes(form.familiarity)
      || form.priorities.length > 3 || new Set(form.priorities).size !== form.priorities.length || form.presentation_acknowledged !== true) {
    throw new Error("Confira cenário, familiaridade, até três prioridades e ciência da apresentação.");
  }
  return { scenario_id: form.scenario_id, familiarity: form.familiarity,
    priorities: [...form.priorities], presentation_acknowledged: true };
}
