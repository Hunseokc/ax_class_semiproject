# 배포 DB 일일 스냅샷 Job 이미지 — 서버(Supabase 17.11)와 같은 주 버전의 pg_dump
FROM postgres:17.11
COPY snapshot.sh /snapshot.sh
RUN sed -i 's/\r$//' /snapshot.sh
ENTRYPOINT ["bash", "/snapshot.sh"]
