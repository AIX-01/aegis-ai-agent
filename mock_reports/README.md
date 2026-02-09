# Mock 보고서 저장 폴더

이 폴더는 Mock 모드에서 생성된 보고서 파일들이 저장되는 위치입니다.

## 구조

```
mock_reports/
└── {event_id}/
    ├── report.pdf
    ├── report.docx
    ├── report.pptx
    └── report.hwp
```

## 참고

- Mock 서버 실행 시 자동으로 하위 폴더가 생성됩니다.
- 실제 운영 환경에서는 MinIO(S3)에 저장됩니다.
- 이 폴더의 내용은 `.gitignore`에 의해 제외됩니다.

