#include <assert.h>
#define __STDC_FORMAT_MACROS
#include <inttypes.h>
#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct FuncType {
  Type* params;
  Type* results;
  size_t param_count;
  size_t result_count;
} FuncType;

int g_tests_run;
int g_tests_passed;
jmp_buf g_jmp_buf;
FuncType* g_func_types;
size_t g_func_type_count;

void run_spec_tests(void);

void error(const char* file, int line, const char* format, ...) {
  va_list args;
  va_start(args, format);
  fprintf(stderr, "%s:%d: assertion failed: ", file, line);
  vfprintf(stderr, format, args);
  va_end(args);
}

#define ASSERT_TRAP(f)                                         \
  do {                                                         \
    g_tests_run++;                                             \
    if (setjmp(g_jmp_buf) != 0) {                              \
      g_tests_passed++;                                        \
    } else {                                                   \
      (void)(f);                                               \
      error(__FILE__, __LINE__, "expected " #f " to trap.\n"); \
    }                                                          \
  } while (0)

#define ASSERT_RETURN(f)                           \
  do {                                             \
    g_tests_run++;                                 \
    if (setjmp(g_jmp_buf) != 0) {                  \
      error(__FILE__, __LINE__, #f " trapped.\n"); \
    } else {                                       \
      f;                                           \
      g_tests_passed++;                            \
    }                                              \
  } while (0)

#define ASSERT_RETURN_T(type, fmt, f, expected)                          \
  do {                                                                   \
    g_tests_run++;                                                       \
    if (setjmp(g_jmp_buf) != 0) {                                        \
      error(__FILE__, __LINE__, #f " trapped.\n");                       \
    } else {                                                             \
      type actual = f;                                                   \
      if (actual == expected) {                                          \
        g_tests_passed++;                                                \
      } else {                                                           \
        error(__FILE__, __LINE__,                                        \
              "in " #f ": expected %" fmt ", got %" fmt ".\n", expected, \
              actual);                                                   \
      }                                                                  \
    }                                                                    \
  } while (0)

#define ASSERT_RETURN_NAN_T(type, itype, fmt, f, kind)                      \
  do {                                                                      \
    g_tests_run++;                                                          \
    if (setjmp(g_jmp_buf) != 0) {                                           \
      error(__FILE__, __LINE__, #f " trapped.\n");                          \
    } else {                                                                \
      type actual = f;                                                      \
      itype iactual;                                                        \
      memcpy(&iactual, &actual, sizeof(iactual));                           \
      if (is_##kind##_nan_##type(iactual)) {                                \
        g_tests_passed++;                                                   \
      } else {                                                              \
        error(__FILE__, __LINE__,                                           \
              "in " #f ": expected result to be a " #kind " nan, got %" fmt \
              ".\n",                                                        \
              iactual);                                                     \
      }                                                                     \
    }                                                                       \
  } while (0)

#define ASSERT_RETURN_I32(f, expected) ASSERT_RETURN_T(u32, "u", f, expected)
#define ASSERT_RETURN_I64(f, expected) ASSERT_RETURN_T(u64, PRIu64, f, expected)
#define ASSERT_RETURN_F32(f, expected) ASSERT_RETURN_T(f32, ".9g", f, expected)
#define ASSERT_RETURN_F64(f, expected) ASSERT_RETURN_T(f64, ".17g", f, expected)

#define ASSERT_RETURN_CANONICAL_NAN_F32(f) \
  ASSERT_RETURN_NAN_T(f32, u32, "08x", f, canonical)
#define ASSERT_RETURN_CANONICAL_NAN_F64(f) \
  ASSERT_RETURN_NAN_T(f64, u64, "016x", f, canonical)
#define ASSERT_RETURN_ARITHMETIC_NAN_F32(f) \
  ASSERT_RETURN_NAN_T(f32, u32, "08x", f, arithmetic)
#define ASSERT_RETURN_ARITHMETIC_NAN_F64(f) \
  ASSERT_RETURN_NAN_T(f64, u64, "016x", f, arithmetic)

static int is_canonical_nan_f32(u32 x) {
  return (x & 0x7fffff) == 0x400000;
}

static int is_canonical_nan_f64(u64 x) {
  return (x & 0xfffffffffffff) == 0x8000000000000;
}

static int is_arithmetic_nan_f32(u32 x) {
  return (x & 0x400000) == 0x400000;
}

static int is_arithmetic_nan_f64(u64 x) {
  return (x & 0xfffffffffffff) == 0x8000000000000;
}

void trap(Trap code) {
  assert(code != TRAP_NONE);
  longjmp(g_jmp_buf, code);
}

static int func_types_are_equal(FuncType* a, FuncType* b) {
  if (a->param_count != b->param_count || a->result_count != b->result_count)
    return 0;
  int i;
  for (i = 0; i < a->param_count; ++i)
    if (a->params[i] != b->params[i])
      return 0;
  for (i = 0; i < a->result_count; ++i)
    if (a->results[i] != b->results[i])
      return 0;
  return 1;
}

u32 register_func_type(u32 param_count, u32 result_count, ...) {
  FuncType func_type;
  func_type.param_count = param_count;
  func_type.params = malloc(param_count * sizeof(Type));
  func_type.result_count = result_count;
  func_type.results = malloc(result_count * sizeof(Type));

  va_list args;
  va_start(args, result_count);

  u32 i;
  for (i = 0; i < param_count; ++i)
    func_type.params[i] = va_arg(args, Type);
  for (i = 0; i < result_count; ++i)
    func_type.results[i] = va_arg(args, Type);
  va_end(args);

  for (i = 0; i < g_func_type_count; ++i) {
    if (func_types_are_equal(&g_func_types[i], &func_type)) {
      free(func_type.params);
      free(func_type.results);
      return i + 1;
    }
  }

  u32 idx = g_func_type_count++;
  g_func_types = realloc(g_func_types, g_func_type_count * sizeof(FuncType));
  g_func_types[idx] = func_type;
  return idx + 1;
}

void allocate_memory(Memory* memory, u32 page_size) {
  memory->len = page_size * 65536;
  memory->data = calloc(memory->len, 1);
}

void allocate_table(Table* table, u32 element_size) {
  table->len = element_size;
  table->data = calloc(table->len, sizeof(Elem));
}

int main(int argc, char** argv) {
  init();
  run_spec_tests();
  fprintf(stderr, "%u/%u tests passed.\n", g_tests_passed, g_tests_run);
  return 0;
}

