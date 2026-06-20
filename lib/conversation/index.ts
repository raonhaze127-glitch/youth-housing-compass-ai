import type { Recommendation } from "../types";

function selectProgram(
  message: string,
  recommendations: Recommendation[],
  contextProgramIds: string[]
) {
  const rank = message.match(/([1-9])\s*번/);
  if (rank) {
    const id = contextProgramIds[Number(rank[1]) - 1];
    return recommendations.find((item) => item.id === id);
  }

  return recommendations.find((program) =>
    program.title.length >= 4 && message.includes(program.title)
  );
}

export function createConversationalAnswer(
  message: string,
  recommendations: Recommendation[],
  contextProgramIds: string[] = []
) {
  const selected = selectProgram(message, recommendations, contextProgramIds);

  if (selected && /자격|조건|가능/.test(message)) {
    return `${selected.title}의 사전 확인 내용입니다. ${selected.eligibility_summary || selected.reasons.join(" ")} 실제 자격은 원문 공고와 제출 서류를 기준으로 확정됩니다.`;
  }

  if (selected && /서류|준비/.test(message)) {
    return selected.required_documents.length
      ? `${selected.title} 준비서류: ${selected.required_documents.join(", ")}. 공고 유형과 개인 상황에 따라 추가 서류가 필요할 수 있습니다.`
      : `${selected.title}의 준비서류가 아직 구조화되지 않았습니다. 카드의 공고 해석 또는 원문 확인을 이용해주세요.`;
  }

  if (selected && /기간|일정|언제|마감/.test(message)) {
    return selected.apply_start && selected.apply_end
      ? `${selected.title} 신청기간은 ${selected.apply_start}부터 ${selected.apply_end}까지이며 현재 상태는 ${selected.status === "open" ? "접수중" : selected.status === "planned" ? "모집예정" : selected.status === "closed" ? "마감" : "일정 확인 필요"}입니다.`
      : `${selected.title}의 신청기간은 아직 확인되지 않았습니다. 원문 공고에서 일정을 확인해주세요.`;
  }

  if (selected && /지원|혜택|얼마|내용/.test(message)) {
    return `${selected.title} 지원내용: ${selected.benefit_summary || selected.summary}`;
  }

  if (selected && /경쟁률/.test(message)) {
    return `${selected.title} 카드의 경쟁률 버튼에서 실제 결과, 지역 이력, 통계 추정치 순으로 확인할 수 있습니다. 출처가 통계 추정치라면 참고값으로만 보세요.`;
  }

  if (selected) {
    return `${selected.title}에 대해 자격, 준비서류, 신청기간, 지원내용 또는 경쟁률을 물어보실 수 있습니다.`;
  }

  if (!recommendations.length) {
    return "현재 조건으로 찾은 공고가 없습니다. 지역, 나이, 무주택 여부와 원하는 지원 유형을 더 자세히 알려주세요.";
  }

  const active = recommendations.filter((item) => item.status === "open").length;
  const planned = recommendations.filter((item) => item.status === "planned").length;
  return `입력한 조건으로 ${recommendations.length}개 공고를 찾았습니다. 접수중 ${active}개, 모집예정 ${planned}개이며 카드의 번호를 사용해 “1번 자격”처럼 이어서 질문할 수 있습니다.`;
}
