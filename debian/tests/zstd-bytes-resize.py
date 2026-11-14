"""Exercise the exact bundled C helper, including shared/immortal bytes, nogil."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import re
import shlex
import subprocess
import sys
import sysconfig
import tempfile
import unittest

source = Path(__file__).resolve().parents[2] / 'contrib/python-zstandard/c-ext/backend_c.c'
helper = re.search(r'^int safe_pybytes_resize\(.*?^}', source.read_text(), re.M | re.S).group()
wrapper = r'''
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
HELPER
static PyObject *resize_bytes(PyObject *self, PyObject *args) {
    Py_ssize_t before, after;
    int shared;
    PyObject *value, *alias;
    if (!PyArg_ParseTuple(args, "nnp", &before, &after, &shared)) return NULL;
    if (before < 0 || after < 0) {
        PyErr_SetString(PyExc_ValueError, "negative size");
        return NULL;
    }
    value = before <= 1 ? PyBytes_FromStringAndSize("x", before)
                        : PyBytes_FromStringAndSize(NULL, before);
    if (!value) return NULL;
    if (before > 1) memset(PyBytes_AS_STRING(value), 'x', before);
    alias = shared ? value : Py_None;
    Py_INCREF(alias);
    if (safe_pybytes_resize(&value, after)) {
        Py_XDECREF(value);
        Py_DECREF(alias);
        return NULL;
    }
    return Py_BuildValue("NN", value, alias);
}
static PyMethodDef methods[] = {
    {"resize", resize_bytes, METH_VARARGS, NULL}, {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_zstd_resize_test", NULL, -1, methods
};
PyMODINIT_FUNC PyInit__zstd_resize_test(void) {
    PyObject *result = PyModule_Create(&module);
#ifdef Py_GIL_DISABLED
    if (result) PyUnstable_Module_SetGIL(result, Py_MOD_GIL_NOT_USED);
#endif
    return result;
}
'''.replace('HELPER', helper)


class BytesResize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='mercurial-zstd-resize-')
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        code = root / 'resize.c'
        code.write_text(wrapper)
        binary = root / ('_zstd_resize_test' + sysconfig.get_config_var('EXT_SUFFIX'))
        command = shlex.split(sysconfig.get_config_var('LDSHARED'))
        command += ['-fPIC', '-I' + sysconfig.get_path('include'), str(code), '-o', str(binary)]
        subprocess.run(command, check=True)
        spec = importlib.util.spec_from_file_location('_zstd_resize_test', binary)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def check_resize(self, before, after, shared):
        result, alias = self.module.resize(before, after, shared)
        self.assertEqual(len(result), after)
        self.assertEqual(result[:min(before, after)], b'x' * min(before, after))
        if shared:
            self.assertEqual(alias, b'x' * before)
        else:
            self.assertIsNone(alias)

    def test_unique_shared_and_immortal_bytes(self):
        for before in (0, 1, 2, 31, 512):
            for after in (0, 1, 17, 1024):
                for shared in (False, True):
                    with self.subTest(before=before, after=after, shared=shared):
                        self.check_resize(before, after, shared)

    def test_parallel_calls_keep_original_shared_bytes(self):
        def exercise(index):
            for _ in range(100):
                self.check_resize(index % 32, (index * 7) % 65, True)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(exercise, range(64)))
        if sysconfig.get_config_var('Py_GIL_DISABLED'):
            self.assertFalse(sys._is_gil_enabled(), 'test wrapper must not enable the GIL')


if __name__ == '__main__':
    unittest.main()
