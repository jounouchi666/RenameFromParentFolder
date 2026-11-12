#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <oleidl.h>
#include <shellapi.h>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <new>
#include <string>
#include <vector>

namespace {
const CLSID handlerId = {0x9f59a969, 0x3cd7, 0x489a, {0xbc, 0x10, 0x82, 0xe5, 0xaf, 0xdb, 0x0f, 0xaa}};
HMODULE module;
std::atomic<long> moduleReferences{0};

std::string Utf8(const std::wstring& value) {
    const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    std::string result(size, '\0');
    WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr);
    return result;
}

HRESULT RenameFiles(HDROP drop) {
    wchar_t modulePath[MAX_PATH];
    const DWORD moduleLength = GetModuleFileNameW(module, modulePath, MAX_PATH);
    if (!moduleLength || moduleLength == MAX_PATH)
        return E_FAIL;
    const auto directory = std::filesystem::path(modulePath).parent_path();
    std::wstring python;
    std::ifstream pythonConfig(directory / L"pythonw.path", std::ios::binary);
    std::string encodedPython((std::istreambuf_iterator<char>(pythonConfig)), {});
    const int pythonLength = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, encodedPython.data(),
        static_cast<int>(encodedPython.size()), nullptr, 0);
    if (!pythonLength)
        return E_FAIL;
    python.resize(pythonLength);
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, encodedPython.data(),
        static_cast<int>(encodedPython.size()), python.data(), pythonLength);

    const UINT count = DragQueryFileW(drop, UINT_MAX, nullptr, 0);
    if (!count)
        return E_INVALIDARG;
    std::string selection;
    for (UINT index = 0; index < count; ++index) {
        std::wstring file(DragQueryFileW(drop, index, nullptr, 0) + 1, L'\0');
        const UINT length = DragQueryFileW(drop, index, file.data(), static_cast<UINT>(file.size()));
        if (!length)
            return E_FAIL;
        file.resize(length);
        selection += Utf8(file) + '\n';
    }

    wchar_t tempDirectory[MAX_PATH], tempFile[MAX_PATH];
    const DWORD tempLength = GetTempPathW(MAX_PATH, tempDirectory);
    if (!tempLength || tempLength >= MAX_PATH || !GetTempFileNameW(tempDirectory, L"RFP", 0, tempFile))
        return E_FAIL;
    std::ofstream stream(tempFile, std::ios::binary);
    stream << selection;
    stream.close();
    if (!stream) {
        DeleteFileW(tempFile);
        return E_FAIL;
    }

    const auto script = directory / L"RenameFromParentFolder.py";
    std::wstring command = L"\"" + python + L"\" \"" + script.wstring() + L"\" --explorer --selection-file \"" + tempFile + L"\"";
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(python.c_str(), command.data(), nullptr, nullptr, FALSE, 0, nullptr,
            directory.c_str(), &startup, &process)) {
        const HRESULT error = HRESULT_FROM_WIN32(GetLastError());
        DeleteFileW(tempFile);
        return error;
    }
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return S_OK;
}

template<typename Interface>
class ComObject : public Interface {
public:
    ComObject() { ++moduleReferences; }
    virtual ~ComObject() { --moduleReferences; }
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** result) override {
        *result = nullptr;
        if (iid != IID_IUnknown && iid != __uuidof(Interface))
            return E_NOINTERFACE;
        *result = static_cast<Interface*>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++references; }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG remaining = --references;
        if (!remaining)
            delete this;
        return remaining;
    }
private:
    std::atomic<ULONG> references{1};
};

class RenameDropTarget final : public ComObject<IDropTarget> {
public:
    HRESULT STDMETHODCALLTYPE DragEnter(IDataObject*, DWORD, POINTL, DWORD* effect) override {
        *effect = DROPEFFECT_COPY;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE DragOver(DWORD, POINTL, DWORD* effect) override {
        *effect = DROPEFFECT_COPY;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE DragLeave() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE Drop(IDataObject* data, DWORD, POINTL, DWORD* effect) override {
        *effect = DROPEFFECT_NONE;
        FORMATETC format{CF_HDROP, nullptr, DVASPECT_CONTENT, -1, TYMED_HGLOBAL};
        STGMEDIUM medium{};
        HRESULT result = data->GetData(&format, &medium);
        if (FAILED(result))
            return result;
        try {
            result = RenameFiles(static_cast<HDROP>(medium.hGlobal));
        } catch (...) {
            result = E_FAIL;
        }
        ReleaseStgMedium(&medium);
        if (SUCCEEDED(result))
            *effect = DROPEFFECT_COPY;
        return result;
    }
};

class DropTargetFactory final : public ComObject<IClassFactory> {
public:
    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID iid, void** result) override {
        *result = nullptr;
        if (outer)
            return CLASS_E_NOAGGREGATION;
        auto* target = new (std::nothrow) RenameDropTarget;
        if (!target)
            return E_OUTOFMEMORY;
        const HRESULT status = target->QueryInterface(iid, result);
        target->Release();
        return status;
    }
    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
        if (lock)
            ++moduleReferences;
        else
            --moduleReferences;
        return S_OK;
    }
};
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH)
        module = instance;
    return TRUE;
}

STDAPI DllCanUnloadNow() {
    return moduleReferences == 0 ? S_OK : S_FALSE;
}

STDAPI DllGetClassObject(REFCLSID clsid, REFIID iid, void** result) {
    *result = nullptr;
    if (clsid != handlerId)
        return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) DropTargetFactory;
    if (!factory)
        return E_OUTOFMEMORY;
    const HRESULT status = factory->QueryInterface(iid, result);
    factory->Release();
    return status;
}
