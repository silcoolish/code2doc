/**
 * Sample C++ module for testing tree-sitter parser
 */

#include <iostream>
#include <string>
#include <vector>
#include <memory>

/**
 * Person class
 */
class Person {
private:
    std::string name;
    int age;

public:
    Person(const std::string& name, int age)
        : name(name), age(age) {}

    std::string greet() const {
        return "Hello, my name is " + name;
    }

    void celebrateBirthday() {
        age++;
    }

    std::string getName() const {
        return name;
    }

    int getAge() const {
        return age;
    }
};

/**
 * Calculator class with history
 */
class Calculator {
private:
    std::vector<double> history;

public:
    Calculator() = default;

    double add(double a, double b) {
        double result = a + b;
        history.push_back(result);
        return result;
    }

    double subtract(double a, double b) {
        double result = a - b;
        history.push_back(result);
        return result;
    }

    std::vector<double> getHistory() const {
        return history;
    }

    void clear() {
        history.clear();
    }
};

/**
 * Processor interface
 */
template<typename T>
class Processor {
public:
    virtual ~Processor() = default;
    virtual T process(const T& input) = 0;
};

/**
 * UpperCase processor
 */
class UpperCaseProcessor : public Processor<std::string> {
public:
    std::string process(const std::string& input) override {
        std::string result;
        for (char c : input) {
            result += std::toupper(c);
        }
        return result;
    }
};

/**
 * Standalone function
 */
std::vector<std::string> processData(const std::vector<std::string>& data) {
    std::vector<std::string> result;
    for (const auto& item : data) {
        std::string processed;
        for (char c : item) {
            processed += std::toupper(c);
        }
        result.push_back(processed);
    }
    return result;
}

/**
 * Namespace with utilities
 */
namespace utils {
    template<typename T>
    T max(T a, T b) {
        return (a > b) ? a : b;
    }

    template<typename T>
    T min(T a, T b) {
        return (a < b) ? a : b;
    }
}

// Using declarations
using utils::max;
using utils::min;
