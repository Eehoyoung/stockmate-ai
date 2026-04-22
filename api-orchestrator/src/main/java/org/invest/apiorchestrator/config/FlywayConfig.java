package org.invest.apiorchestrator.config;

import org.flywaydb.core.Flyway;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.BeanFactory;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.beans.factory.config.BeanFactoryPostProcessor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;

import javax.sql.DataSource;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * Spring Boot 4.0 에서 Flyway 자동 구성이 동작하지 않는 경우를 위한 명시적 Bean 구성.
 * FlywayAutoConfiguration 이 정상 로드되면 이 Bean 은 조건에 의해 스킵될 수 있으나,
 * 안전망으로 유지한다.
 */
@Configuration
public class FlywayConfig {

    private static final Logger log = LoggerFactory.getLogger(FlywayConfig.class);

    @Bean(initMethod = "migrate")
    public Flyway flyway(DataSource dataSource) {
        log.info("[Flyway] 수동 마이그레이션 시작 (classpath:db/migration)");
        return Flyway.configure()
                .dataSource(dataSource)
                .locations("classpath:db/migration")
                .baselineOnMigrate(true)
                .baselineVersion("1")
                .validateOnMigrate(false)   // update 모드와 병행이므로 검증 비활성화
                .outOfOrder(false)
                .load();
    }

    @Bean
    public static BeanFactoryPostProcessor entityManagerFactoryDependsOnFlyway() {
        return beanFactory -> {
            String[] entityManagerFactoryBeanNames = beanFactory.getBeanNamesForType(
                    LocalContainerEntityManagerFactoryBean.class, true, false);

            for (String beanName : entityManagerFactoryBeanNames) {
                String beanDefinitionName = beanName.startsWith(BeanFactory.FACTORY_BEAN_PREFIX)
                        ? beanName.substring(BeanFactory.FACTORY_BEAN_PREFIX.length())
                        : beanName;
                BeanDefinition beanDefinition = beanFactory.getBeanDefinition(beanDefinitionName);
                Set<String> dependsOn = new LinkedHashSet<>();
                String[] existingDependsOn = beanDefinition.getDependsOn();
                if (existingDependsOn != null) {
                    dependsOn.addAll(Set.of(existingDependsOn));
                }
                dependsOn.add("flyway");
                beanDefinition.setDependsOn(dependsOn.toArray(String[]::new));
            }
        };
    }
}
