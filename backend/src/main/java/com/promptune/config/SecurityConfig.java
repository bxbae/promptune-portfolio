package com.promptune.config;

import com.promptune.service.OAuth2UserService;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import java.util.List;
import java.util.Arrays;
import org.springframework.beans.factory.annotation.Value;

/** Spring Security 설정. 로컬(JWT) + 소셜(OAuth2) 로그인. */
@Configuration
public class SecurityConfig {

    private final JwtAuthFilter jwtFilter;
    private final OAuth2UserService oAuth2UserService;
    private final OAuth2SuccessHandler oAuth2SuccessHandler;

    @Value("${app.cors-origins:http://localhost:3000}")
    private String corsOrigins;

    public SecurityConfig(JwtAuthFilter jwtFilter,
                          OAuth2UserService oAuth2UserService,
                          OAuth2SuccessHandler oAuth2SuccessHandler) {
        this.jwtFilter = jwtFilter;
        this.oAuth2UserService = oAuth2UserService;
        this.oAuth2SuccessHandler = oAuth2SuccessHandler;
    }

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOrigins(Arrays.stream(corsOrigins.split(","))
                .map(String::trim)
                .filter(origin -> !origin.isEmpty())
                .toList());
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        config.setAllowCredentials(true);

        // 2026-08-27: MS 연동(OAuth) 콜백에서 "Invalid CORS request"가 그대로
        // 응답 본문에 노출되는 오류가 확인됨. MicrosoftGraphService.createAuthorizationUrl()이
        // ResponseMode.FORM_POST를 쓰기 때문에, 로그인 완료 후 Microsoft가 렌더링하는
        // 중간 페이지(login.microsoftonline.com)가 CSP sandbox로 격리돼 있어 이 페이지가
        // 우리 콜백 URL로 보내는 POST 요청의 Origin 헤더가 문자열 그대로 "null"이 된다 -
        // 이건 잘 알려진 동작이라 allowedOrigins("null") 자체는 올바르게 이미 반영돼 있었음.
        // 문제는 MicrosoftIntegrationController.callback()이 @RequestMapping(method =
        // {GET, POST})로 GET/POST 둘 다 받도록 만들어져 있는데(Microsoft 응답 모드가
        // query로 바뀌거나, 재시도/리다이렉트 과정에서 GET으로 들어오는 경우까지 대비),
        // 여기 CORS 설정은 allowedMethods를 POST 하나로만 좁혀놔서 - 실제로 GET으로
        // 들어오는 케이스(또는 Microsoft/프록시 쪽에서 예상과 다르게 GET을 쓰는 케이스)는
        // Spring의 DefaultCorsProcessor가 메서드 불일치로 요청 자체를 거부해서
        // "Invalid CORS request"를 그대로 응답 본문에 써버린다. 컨트롤러가 실제로
        // 허용하는 메서드(GET, POST)와 CORS 설정을 일치시킨다.
        CorsConfiguration microsoftCallback = new CorsConfiguration();
        microsoftCallback.setAllowedOrigins(List.of("null"));
        microsoftCallback.setAllowedMethods(List.of("GET", "POST"));
        microsoftCallback.setAllowedHeaders(List.of("*"));
        microsoftCallback.setAllowCredentials(false);

        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();

        source.registerCorsConfiguration(
                "/api/integrations/microsoft/callback",
                microsoftCallback
        );

        source.registerCorsConfiguration("/**", config);
        return source;
    }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        // /api/** 요청이 인증 안 됐을 때는 소셜로그인용 /login 페이지로 리다이렉트하지 않고
        // 그냥 401만 내려주기 위한 전용 진입점. (안 하면 fetch가 리다이렉트를 타다가
        // "Failed to fetch"로 실패하고, 토큰이 없을 때 /login 자체가 인증이 필요한 걸로
        // 잘못 막혀있으면 무한 리다이렉트(ERR_TOO_MANY_REDIRECTS)까지 났었음)
        org.springframework.security.web.AuthenticationEntryPoint apiEntryPoint =
                (request, response, authException) ->
                        response.sendError(jakarta.servlet.http.HttpServletResponse.SC_UNAUTHORIZED, "인증이 필요합니다.");

        http
            .cors(cors -> {})
            .csrf(csrf -> csrf.disable())
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .exceptionHandling(ex -> ex.defaultAuthenticationEntryPointFor(
                    apiEntryPoint,
                    new org.springframework.security.web.util.matcher.AntPathRequestMatcher("/api/**")))
            .authorizeHttpRequests(auth -> auth
                // preflight(OPTIONS)는 브라우저가 Authorization 헤더 없이 보내므로 항상 인증 예외
                // (없으면 CORS 이전에 Security가 403으로 먼저 막아버림 - 실제로 PATCH 요청에서 이 문제로 preflight 자체가 403 났음)
                .requestMatchers(org.springframework.http.HttpMethod.OPTIONS, "/**").permitAll()
                .requestMatchers("/api/auth/**", "/health", "/actuator/**", "/error").permitAll()
                // 소셜로그인이 3개(구글/네이버/카카오) 등록돼있어서 미인증 브라우저 요청은
                // 스프링이 자동으로 "/login" 페이지로 리다이렉트함 — 이 경로 자체를 막아두면
                // /login → 인증필요 → /login으로 리다이렉트 → ... 무한루프가 났었어서 "/login/**"로 열어둠
                .requestMatchers("/oauth2/**", "/login/**").permitAll()
                .requestMatchers("/api/integrations/microsoft/callback").permitAll()
                .anyRequest().authenticated()
            )
            .oauth2Login(oauth -> oauth
                .userInfoEndpoint(u -> u.userService(oAuth2UserService))
                .successHandler(oAuth2SuccessHandler)
            )
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
