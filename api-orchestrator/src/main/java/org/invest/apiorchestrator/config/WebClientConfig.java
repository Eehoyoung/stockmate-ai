package org.invest.apiorchestrator.config;

import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
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
    private final TossInvestProperties tossProperties;

    public WebClientConfig(KiwoomProperties properties, TossInvestProperties tossProperties) {
        this.properties = properties;
        this.tossProperties = tossProperties;
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
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .filter(logRequest())
                .build();
    }

    private ExchangeFilterFunction logRequest() {
        return ExchangeFilterFunction.ofRequestProcessor(request -> {
            return Mono.just(request);
        });
    }

    /** 토스증권 Open API 전용 WebClient. 조회 전용(시세/종목/시장정보/랭킹/지표) 트래픽만 사용한다. */
    @Bean
    public WebClient tossWebClient() {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 5000)
                .responseTimeout(Duration.ofSeconds(10))
                .doOnConnected(conn ->
                        conn.addHandlerLast(new ReadTimeoutHandler(10, TimeUnit.SECONDS))
                                .addHandlerLast(new WriteTimeoutHandler(10, TimeUnit.SECONDS)));

        String baseUrl = tossProperties.getBaseUrl() != null && !tossProperties.getBaseUrl().isBlank()
                ? tossProperties.getBaseUrl() : "https://openapi.tossinvest.com";

        return WebClient.builder()
                .baseUrl(baseUrl)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }

    /** 관리자 대시보드가 타 서비스(/health) 조회에 쓰는 범용 WebClient. 짧은 타임아웃으로 한 서비스 지연이 전체 응답을 막지 않게 한다. */
    @Bean
    public WebClient internalWebClient() {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 1500)
                .responseTimeout(Duration.ofSeconds(3))
                .doOnConnected(conn ->
                        conn.addHandlerLast(new ReadTimeoutHandler(3, TimeUnit.SECONDS))
                                .addHandlerLast(new WriteTimeoutHandler(3, TimeUnit.SECONDS)));
        return WebClient.builder()
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
