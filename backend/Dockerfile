FROM gradle:8.10-jdk21 AS build
WORKDIR /app
COPY . .
RUN gradle bootJar --no-daemon

FROM eclipse-temurin:21-jre
WORKDIR /app

# 2026-09-07: 데모 모드에서 "PDF로 줘"처럼 명시적으로 PDF를 요청하면,
# 사내 서식 원본(docx/pptx)을 표/색상이 그대로 보이는 PDF로 변환해서
# 내려준다(AiServiceClient.demoTemplateFileAsPdf). 전체 libreoffice
# 메타패키지 대신 Writer/Impress 변환에 필요한 구성요소만 설치해서
# 이미지 용량 증가를 줄인다. fonts-nanum은 문서에서 쓰는 "맑은 고딕"
# 대체 한글 폰트가 없어서 글자가 깨지는(네모/빈칸) 것을 막기 위해 필요하다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
        libreoffice-impress \
        fonts-nanum \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/build/libs/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "app.jar"]
