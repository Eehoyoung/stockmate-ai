package org.invest.apiorchestrator.domain;

import jakarta.persistence.*;
import lombok.*;
import org.springframework.data.annotation.LastModifiedDate;
import org.springframework.data.jpa.domain.support.AuditingEntityListener;

import java.time.LocalDateTime;

@Entity
@Table(name = "kiwoom_tokens")
@EntityListeners(AuditingEntityListener.class)
@Getter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class KiwoomToken {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "access_token", nullable = false, length = 2000)
    private String accessToken;

    @Column(name = "token_type", length = 20)
    @Builder.Default
    private String tokenType = "Bearer";

    @Column(name = "expires_at", nullable = false)
    private LocalDateTime expiresAt;

    @Column(name = "is_active")
    @Builder.Default
    private boolean active = true;

    @LastModifiedDate
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    public boolean isExpired() {
        return LocalDateTime.now().isAfter(expiresAt.minusMinutes(10));
    }

    public String getBearerToken() {
        return tokenType + " " + accessToken;
    }

    public void deactivate() {
        this.active = false;
    }
}
