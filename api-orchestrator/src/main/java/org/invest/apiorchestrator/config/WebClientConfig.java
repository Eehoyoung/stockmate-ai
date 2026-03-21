package org.invest.apiorchestrator.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.ExchangeFilterFunction;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;
import reactor.netty.http.client.HttpClient;

import java.time.Duration;
import java.util.concurrent.TimeUnit;

@Configuration
public class WebClientConfig {

    private final KiwoomProperties properties;

    public WebClientConfig(KiwoomProperties properties) {
        this.properties = properties;
    }

    @Bean
    public WebClient kiwoomWebClient() {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 5000)
                .responseTimeout(Duration.ofSeconds(10))
                .doOnConnected(conn ->
                        conn.addHandlerLast(new ReadTimeoutHandler(10, TimeUnit.SECONDS))
                                .addHandlerLast(new WriteTimeoutHandler(10, TimeUnit.SECONDS)));

        // 실전/모의 환경 분기 (KIWOOM_MODE=real|mock)
        String configuredBaseUrl = properties.getApi().getBaseUrl();
        String effectiveBaseUrl;
        if ("real".equalsIgnoreCase(properties.getMode())) {
            effectiveBaseUrl = configuredBaseUrl != null && !configuredBaseUrl.isBlank()
                    ? configuredBaseUrl : "https://api.kiwoom.com";
        } else {
            effectiveBaseUrl = configuredBaseUrl != null && !configuredBaseUrl.isBlank()
                    ? configuredBaseUrl : "https://mockapi.kiwoom.com";
        }

        return WebClient.builder()
                .baseUrl(effectiveBaseUrl)
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .filter(logRequest())
                .build();
    }

    private ExchangeFilterFunction logRequest() {
        return ExchangeFilterFunction.ofRequestProcessor(request -> {
            return Mono.just(request);
        });
    }
}
