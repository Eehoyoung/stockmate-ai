package org.invest.apiorchestrator;

import io.github.cdimascio.dotenv.Dotenv;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

@SpringBootApplication
@EnableScheduling
public class ApiOrchestratorApplication {
    public static void main(String[] args) {
        loadDotenv();
        SpringApplication.run(ApiOrchestratorApplication.class, args);
    }

    /**
     * dotenv-java는 현재 작업 디렉토리에서만 .env를 탐색합니다.
     * IntelliJ/Gradle 실행 환경에 따라 작업 디렉토리가 다를 수 있으므로
     * 후보 경로를 순서대로 시도합니다.
     */
    private static void loadDotenv() {
        String workDir = System.getProperty("user.dir");
        String[] candidates = {
                workDir,                                    // 현재 작업 디렉토리 (api-orchestrator/ or 프로젝트 루트)
                workDir + "/api-orchestrator",              // 프로젝트 루트에서 실행 시
                Paths.get(workDir, "..").normalize().toString() // 상위 디렉토리
        };

        for (String dir : candidates) {
            Path envFile = Paths.get(dir, ".env");
            if (Files.exists(envFile)) {
                System.out.println("[dotenv] .env 로드: " + envFile.toAbsolutePath());
                Dotenv dotenv = Dotenv.configure()
                        .directory(dir)
                        .ignoreIfMissing()
                        .load();
                dotenv.entries().forEach(e -> {
                    if (System.getenv(e.getKey()) == null) {
                        System.setProperty(e.getKey(), e.getValue());
                    }
                });
                return; // 첫 번째로 발견한 .env 만 로드
            }
        }
        System.err.println("[dotenv] .env 파일을 찾지 못했습니다. 환경변수가 OS 레벨에 설정되어 있는지 확인하세요.");
        System.err.println("[dotenv] 탐색 경로: " + String.join(", ", candidates));
    }
}
