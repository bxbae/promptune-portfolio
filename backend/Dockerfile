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

# 2026-09-07: Render 프리티어는 CPU가 매우 제한적이다(공유/스로틀). JVM
# 기본값(C2 JIT까지 다 켠 티어드 컴파일)은 부팅 초반 CPU를 많이 써서 오히려
# 콜드 스타트를 더 느리게 만든다. -XX:TieredStopAtLevel=1로 C1(빠른 컴파일)
# 까지만 쓰게 하면 이런 트래픽 적은 데모 앱에서는 처리량 손해가 거의 없이
# 부팅 CPU 사용량을 줄일 수 있다 - Render 포트 스캔 타임아웃(Timed Out) 완화용.
ENTRYPOINT ["java", "-XX:TieredStopAtLevel=1", "-jar", "app.jar"]
