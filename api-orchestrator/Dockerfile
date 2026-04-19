FROM eclipse-temurin:25-jdk AS builder
WORKDIR /build

# 의존성 캐시 레이어 분리
COPY gradlew gradlew.bat settings.gradle build.gradle ./
COPY gradle/ gradle/
RUN sed -i 's/\r$//' gradlew && chmod +x gradlew
RUN ./gradlew dependencies --no-daemon -q || true

COPY src/ src/
RUN ./gradlew bootJar -x test --no-daemon -q

# ── runtime ──
FROM eclipse-temurin:25-jdk
WORKDIR /app

ENV TZ=Asia/Seoul

COPY --from=builder /build/build/libs/*.jar app.jar

RUN mkdir -p logs

EXPOSE 8080

ENTRYPOINT ["java", "-Duser.timezone=Asia/Seoul", "--enable-native-access=ALL-UNNAMED", "-jar", "app.jar"]


