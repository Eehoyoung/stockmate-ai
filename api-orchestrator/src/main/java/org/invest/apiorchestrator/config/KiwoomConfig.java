package org.invest.apiorchestrator.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

@Configuration
public class KiwoomConfig {

    @Bean
    public RestTemplate restTemplate() {
        return new RestTemplate();
    }
}
