package org.invest.apiorchestrator;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class ApiOrchestratorApplication {
    public static void main(String[] args) {
        SpringApplication.run(ApiOrchestratorApplication.class, args);
    }
}
