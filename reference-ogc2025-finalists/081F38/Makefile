CXX = g++
CXXFLAGS = -fPIC -O2 -std=c++17
LDFLAGS = -shared

# Gurobi 설치 경로
GUROBI_DIR = /opt/gurobi1201/linux64

INCLUDES = -I$(GUROBI_DIR)/include
LIBS = -L$(GUROBI_DIR)/lib -lgurobi_c++ -lgurobi120 -lm

TARGET = yjr_solver.so
SRCS = yjr_solver.cpp
OBJS = $(SRCS:.cpp=.o)

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CXX) $(CXXFLAGS) $(INCLUDES) $(LDFLAGS) -o $@ $< $(LIBS)

clean:
	rm -f $(OBJS) $(TARGET)

.PHONY: all clean