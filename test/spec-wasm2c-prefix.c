#define __STDC_FORMAT_MACROS
#include <assert.h>
#include <inttypes.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

void error(const char* format, ...) {
  va_list args;
  va_start(args, format);
  fprintf(stderr, "assertion failed: ");
  vfprintf(stderr, format, args);
  va_end(args);
}

#define ASSERT_TRAP(f)                     \
  do {                                     \
    total++;                               \
    jmp_buf buf;                           \
    if (setjmp(buf) != 0) {                \
      passed++;                            \
    } else {                               \
      (void)(f);                           \
      error("expected " #f " to trap.\n"); \
    }                                      \
  } while (0)

#define ASSERT_RETURN(f)       \
  do {                         \
    total++;                   \
    jmp_buf buf;               \
    if (setjmp(buf) != 0) {    \
      error(#f " trapped.\n"); \
    } else {                   \
      f;                       \
      passed++;                \
    }                          \
  } while (0)

#define ASSERT_RETURN_T(type, fmt, f, expected)      \
  do {                                               \
    total++;                                         \
    jmp_buf buf;                                     \
    if (setjmp(buf) != 0) {                          \
      error(#f " trapped.\n");                       \
    } else {                                         \
      type actual = f;                               \
      if (actual == expected) {                      \
        passed++;                                    \
      } else {                                       \
        error("expected %" fmt ", got %" fmt ".\n"); \
      }                                              \
    }                                                \
  } while (0)

#define ASSERT_RETURN_I32(f, expected) ASSERT_RETURN_T(u32, "u", f, expected)
#define ASSERT_RETURN_I64(f, expected) ASSERT_RETURN_T(u64, PRIu64, f, expected)
#define ASSERT_RETURN_F32(f, expected) ASSERT_RETURN_T(f32, ".9g", f, expected)
#define ASSERT_RETURN_F64(f, expected) ASSERT_RETURN_T(f64, ".17g", f, expected)

int total;
int passed;
void run_tests(void);

int main(int argc, char** argv) {
  run_tests();
  fprintf(stderr, "%u/%u tests passed.", passed, total);
  return 0;
}

