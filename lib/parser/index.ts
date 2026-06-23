import type { UserProfile } from "../types";

const REGIONS = ["서울", "경기", "인천", "부산", "대구", "광주", "대전", "울산", "세종"];
const SEOUL_DISTRICTS = [
  "강남구",
  "강동구",
  "강북구",
  "강서구",
  "관악구",
  "광진구",
  "구로구",
  "금천구",
  "노원구",
  "도봉구",
  "동대문구",
  "동작구",
  "마포구",
  "서대문구",
  "서초구",
  "성동구",
  "성북구",
  "송파구",
  "양천구",
  "영등포구",
  "용산구",
  "은평구",
  "종로구",
  "중구",
  "중랑구"
];
const GYEONGGI_DISTRICTS = [
  "수원시", "성남시", "고양시", "용인시", "부천시", "안산시", "남양주시", "안양시",
  "화성시", "평택시", "의정부시", "시흥시", "파주시", "김포시", "광명시", "광주시",
  "군포시", "오산시", "이천시", "양주시", "구리시", "안성시", "포천시", "의왕시",
  "하남시", "여주시", "동두천시", "과천시", "가평군", "양평군", "연천군"
];

export function parseUserInput(text: string): UserProfile {
  const normalized = text.trim();
  const ageMatch = normalized.match(/(\d{2})\s*(세|살|만)/);
  const childAgeMatch =
    normalized.match(/(\d{1,2})\s*(?:세|살)\s*(?:아기|아이|자녀)/) ??
    normalized.match(/(?:아기|아이|자녀)\s*(\d{1,2})\s*(?:세|살)/);
  const incomeMatch = normalized.match(/(?:월소득|월급|소득|수입)\s*(\d{2,4})\s*(만\s*원|만원|원)?/);
  const region = REGIONS.find((item) => normalized.includes(item));
  const district = [...SEOUL_DISTRICTS, ...GYEONGGI_DISTRICTS].find((item) =>
    normalized.includes(item)
  );
  const homeless = /무주택|집\s*없|자가\s*없/.test(normalized)
    ? true
    : /1주택|자가|주택\s*보유/.test(normalized)
      ? false
      : undefined;
  const householdType = /신혼|혼인|결혼|예비부부/.test(normalized)
    ? "newlywed"
    : /청년|사회초년|직장인|대학생|취준/.test(normalized)
      ? "youth"
      : "unknown";
  const numericIncome = incomeMatch ? Number(incomeMatch[1]) : undefined;
  const incomeLevel =
    /저소득|소득이\s*낮|기초생활|차상위|중위소득/.test(normalized) ||
    (numericIncome !== undefined && numericIncome <= 250)
      ? "low"
      : /고소득|소득이\s*높|월급\s*많/.test(normalized) ||
          (numericIncome !== undefined && numericIncome >= 500)
        ? "high"
        : numericIncome !== undefined || /직장인|월급|소득|수입/.test(normalized)
          ? "middle"
          : "unknown";
  const interests = [
    /월세|월세지원|임차료/.test(normalized) ? "월세" : "",
    /전세|보증금/.test(normalized) ? "전세" : "",
    /공공임대|매입임대|국민임대|영구임대|행복주택|통합공공임대|임대주택|공공주택/.test(normalized)
      ? "공공임대"
      : ""
  ].filter(Boolean);

  return {
    region,
    district,
    age: ageMatch ? Number(ageMatch[1]) : undefined,
    homeless,
    incomeLevel,
    householdType,
    children: childAgeMatch ? [{ age: Number(childAgeMatch[1]) }] : undefined,
    interests,
    rawText: normalized
  };
}
