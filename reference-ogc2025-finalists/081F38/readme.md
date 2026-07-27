### so 파일 컴파일 방법은 두 가지 입니다.
1. 다음의 명령어로 컴파일합니다.
    
    `g++ -fPIC -O2 -std=c++17 -I/opt/gurobi1201/linux64/include -shared -o yjr_solver.so yjr_solver.cpp -L/opt/gurobi1201/linux64/lib -lgurobi_c++ -lgurobi120 -lm`

2. Makefile 을 이용한 빌드:
    
    프로젝트 디렉토리에서 `make` 명령어를 실행하면 자동으로 컴파일됩니다.