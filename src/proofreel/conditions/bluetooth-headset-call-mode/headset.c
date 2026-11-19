#include <CoreAudio/AudioServerPlugIn.h>
#include <dispatch/dispatch.h>
#include <mach/mach_time.h>
#include <pthread.h>
#include <string.h>

#ifndef CALL_RATE
#define CALL_RATE 24000.0
#endif
#define IDLE_RATE 48000.0
#define PERIOD 16384
#define BACK_TO_IDLE_NS (2 * NSEC_PER_SEC)

enum { PLUGIN = kAudioObjectPlugInObject, DEVICE = 2, STREAM = 3 };

static AudioServerPlugInHostRef host;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static Float64 rate = IDLE_RATE;
static UInt32 running;
static UInt64 generation, anchor, stamps;
static Float64 ticksPerFrame;
static UInt32 noise = 1;
static const Float64 rates[] = {16000.0, 24000.0, 48000.0};

#define DEVICE_UID "proofreel.headset"
#define DEVICE_NAME "Headset (proofreel)"
#define MAKER "proofreel"

static void setRate(Float64 value) {
    struct mach_timebase_info base;
    mach_timebase_info(&base);
    rate = value;
    ticksPerFrame = 1e9 * base.denom / base.numer / value;
}

// WHY: a Bluetooth headset changes the rate through the HAL's configuration change, as a real driver does,
// so clients get the same notifications and the same stale-format window.
static void requestRate(Float64 value) {
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        if (host && value != rate) host->RequestDeviceConfigurationChange(host, DEVICE, (UInt64)value, NULL);
    });
}

static AudioStreamBasicDescription format(Float64 value) {
    return (AudioStreamBasicDescription){value, kAudioFormatLinearPCM,
        kAudioFormatFlagIsFloat | kAudioFormatFlagsNativeEndian | kAudioFormatFlagIsPacked, 4, 1, 4, 1, 32, 0};
}

typedef struct { const char *text; UInt32 size; union { UInt32 u[8]; Float64 f; AudioValueRange r[3];
    AudioStreamBasicDescription d; AudioStreamRangedDescription rd[3]; } v; } Value;

static Boolean value(AudioObjectID object, const AudioObjectPropertyAddress *a, Value *out) {
    memset(out, 0, sizeof *out);
    AudioObjectPropertySelector s = a->mSelector;
    Boolean input = a->mScope != kAudioObjectPropertyScopeOutput;
#define U(x) do { out->v.u[0] = (x); out->size = 4; return true; } while (0)
#define IDS(n, ...) do { UInt32 ids[] = {__VA_ARGS__}; memcpy(out->v.u, ids, 4 * (n)); out->size = 4 * (n); return true; } while (0)
#define TEXT(t) do { out->text = (t); out->size = sizeof(CFStringRef); return true; } while (0)
    switch (object) {
    case PLUGIN:
        switch (s) {
        case kAudioObjectPropertyBaseClass: U(kAudioObjectClassID);
        case kAudioObjectPropertyClass: U(kAudioPlugInClassID);
        case kAudioObjectPropertyOwner: U(kAudioObjectUnknown);
        case kAudioObjectPropertyManufacturer: TEXT(MAKER);
        case kAudioObjectPropertyOwnedObjects: case kAudioPlugInPropertyDeviceList: IDS(1, DEVICE);
        case kAudioPlugInPropertyBoxList: out->size = 0; return true;
        case kAudioPlugInPropertyTranslateUIDToDevice: case kAudioPlugInPropertyTranslateUIDToBox: U(kAudioObjectUnknown);
        case kAudioPlugInPropertyResourceBundle: TEXT("");
        }
        return false;
    case DEVICE:
        switch (s) {
        case kAudioObjectPropertyBaseClass: U(kAudioObjectClassID);
        case kAudioObjectPropertyClass: U(kAudioDeviceClassID);
        case kAudioObjectPropertyOwner: U(PLUGIN);
        case kAudioObjectPropertyName: TEXT(DEVICE_NAME);
        case kAudioObjectPropertyManufacturer: TEXT(MAKER);
        case kAudioDevicePropertyDeviceUID: TEXT(DEVICE_UID);
        case kAudioDevicePropertyModelUID: TEXT(DEVICE_UID ".model");
        case kAudioObjectPropertyOwnedObjects: if (input) IDS(1, STREAM); out->size = 0; return true;
        case kAudioDevicePropertyStreams: if (input) IDS(1, STREAM); out->size = 0; return true;
        case kAudioObjectPropertyControlList: out->size = 0; return true;
        case kAudioDevicePropertyTransportType: U(kAudioDeviceTransportTypeBluetooth);
        case kAudioDevicePropertyRelatedDevices: IDS(1, DEVICE);
        case kAudioDevicePropertyClockDomain: U(0);
        case kAudioDevicePropertyDeviceIsAlive: U(1);
        case kAudioDevicePropertyDeviceIsRunning: U(running > 0);
        case kAudioDevicePropertyDeviceCanBeDefaultDevice: U(input);
        case kAudioDevicePropertyDeviceCanBeDefaultSystemDevice: U(0);
        case kAudioDevicePropertyLatency: case kAudioDevicePropertySafetyOffset: U(0);
        case kAudioDevicePropertyIsHidden: U(0);
        case kAudioDevicePropertyZeroTimeStampPeriod: U(PERIOD);
        case kAudioDevicePropertyPreferredChannelsForStereo: IDS(2, 1, 1);
        case kAudioDevicePropertyNominalSampleRate: out->v.f = rate; out->size = 8; return true;
        case kAudioDevicePropertyAvailableNominalSampleRates:
            for (int i = 0; i < 3; i++) out->v.r[i] = (AudioValueRange){rates[i], rates[i]};
            out->size = sizeof(AudioValueRange) * 3; return true;
        }
        return false;
    case STREAM:
        switch (s) {
        case kAudioObjectPropertyBaseClass: U(kAudioObjectClassID);
        case kAudioObjectPropertyClass: U(kAudioStreamClassID);
        case kAudioObjectPropertyOwner: U(DEVICE);
        case kAudioObjectPropertyOwnedObjects: out->size = 0; return true;
        case kAudioStreamPropertyIsActive: U(1);
        case kAudioStreamPropertyDirection: U(1);
        case kAudioStreamPropertyTerminalType: U(kAudioStreamTerminalTypeHeadsetMicrophone);
        case kAudioStreamPropertyStartingChannel: U(1);
        case kAudioStreamPropertyLatency: U(0);
        case kAudioStreamPropertyVirtualFormat: case kAudioStreamPropertyPhysicalFormat:
            out->v.d = format(rate); out->size = sizeof(AudioStreamBasicDescription); return true;
        case kAudioStreamPropertyAvailableVirtualFormats: case kAudioStreamPropertyAvailablePhysicalFormats:
            for (int i = 0; i < 3; i++) out->v.rd[i] = (AudioStreamRangedDescription){format(rates[i]), {rates[i], rates[i]}};
            out->size = sizeof(AudioStreamRangedDescription) * 3; return true;
        }
        return false;
    }
    return false;
}

static Boolean HasProperty(AudioServerPlugInDriverRef d, AudioObjectID o, pid_t p, const AudioObjectPropertyAddress *a) {
    Value v;
    return value(o, a, &v);
}

static OSStatus IsPropertySettable(AudioServerPlugInDriverRef d, AudioObjectID o, pid_t p,
                                   const AudioObjectPropertyAddress *a, Boolean *out) {
    Value v;
    if (!value(o, a, &v)) return kAudioHardwareUnknownPropertyError;
    *out = (o == DEVICE && a->mSelector == kAudioDevicePropertyNominalSampleRate) ||
           (o == STREAM && (a->mSelector == kAudioStreamPropertyVirtualFormat || a->mSelector == kAudioStreamPropertyPhysicalFormat));
    return 0;
}

static OSStatus GetPropertyDataSize(AudioServerPlugInDriverRef d, AudioObjectID o, pid_t p,
                                    const AudioObjectPropertyAddress *a, UInt32 qs, const void *q, UInt32 *out) {
    Value v;
    if (!value(o, a, &v)) return kAudioHardwareUnknownPropertyError;
    *out = v.size;
    return 0;
}

static OSStatus GetPropertyData(AudioServerPlugInDriverRef d, AudioObjectID o, pid_t p, const AudioObjectPropertyAddress *a,
                                UInt32 qs, const void *q, UInt32 size, UInt32 *outSize, void *out) {
    Value v;
    pthread_mutex_lock(&lock);
    Boolean known = value(o, a, &v);
    pthread_mutex_unlock(&lock);
    if (!known) return kAudioHardwareUnknownPropertyError;
    if (a->mSelector == kAudioPlugInPropertyTranslateUIDToDevice && q && qs == sizeof(CFStringRef))
        v.v.u[0] = CFStringCompare(*(CFStringRef *)q, CFSTR(DEVICE_UID), 0) == kCFCompareEqualTo ? DEVICE : kAudioObjectUnknown;
    if (v.text) {
        if (size < sizeof(CFStringRef)) return kAudioHardwareBadPropertySizeError;
        *(CFStringRef *)out = CFStringCreateWithCString(NULL, v.text, kCFStringEncodingUTF8);
        *outSize = sizeof(CFStringRef);
        return 0;
    }
    *outSize = size < v.size ? size : v.size;
    memcpy(out, &v.v, *outSize);
    return 0;
}

static OSStatus SetPropertyData(AudioServerPlugInDriverRef d, AudioObjectID o, pid_t p, const AudioObjectPropertyAddress *a,
                                UInt32 qs, const void *q, UInt32 size, const void *in) {
    Float64 wanted;
    if (o == DEVICE && a->mSelector == kAudioDevicePropertyNominalSampleRate && size == sizeof(Float64))
        wanted = *(const Float64 *)in;
    else if (o == STREAM && size == sizeof(AudioStreamBasicDescription))
        wanted = ((const AudioStreamBasicDescription *)in)->mSampleRate;
    else
        return kAudioHardwareUnsupportedOperationError;
    if (wanted != 16000.0 && wanted != 24000.0 && wanted != 48000.0) return kAudioDeviceUnsupportedFormatError;
    requestRate(wanted);
    return 0;
}

static OSStatus StartIO(AudioServerPlugInDriverRef d, AudioObjectID device, UInt32 client) {
    pthread_mutex_lock(&lock);
    if (running++ == 0) {
        anchor = mach_absolute_time();
        stamps = 0;
        generation++;
        requestRate(CALL_RATE);
    }
    pthread_mutex_unlock(&lock);
    return 0;
}

static OSStatus StopIO(AudioServerPlugInDriverRef d, AudioObjectID device, UInt32 client) {
    pthread_mutex_lock(&lock);
    if (running && --running == 0) {
        UInt64 mine = ++generation;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, BACK_TO_IDLE_NS), dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            if (generation == mine && !running) requestRate(IDLE_RATE);
        });
    }
    pthread_mutex_unlock(&lock);
    return 0;
}

static OSStatus PerformDeviceConfigurationChange(AudioServerPlugInDriverRef d, AudioObjectID device, UInt64 action, void *info) {
    pthread_mutex_lock(&lock);
    setRate((Float64)action);
    anchor = mach_absolute_time();
    stamps = 0;
    pthread_mutex_unlock(&lock);
    return 0;
}

static OSStatus AbortDeviceConfigurationChange(AudioServerPlugInDriverRef d, AudioObjectID device, UInt64 action, void *info) {
    return 0;
}

static OSStatus GetZeroTimeStamp(AudioServerPlugInDriverRef d, AudioObjectID device, UInt32 client,
                                 Float64 *sampleTime, UInt64 *hostTime, UInt64 *seed) {
    pthread_mutex_lock(&lock);
    Float64 ticksPerPeriod = ticksPerFrame * PERIOD;
    if (anchor + (stamps + 1) * ticksPerPeriod <= mach_absolute_time()) stamps++;
    *sampleTime = (Float64)stamps * PERIOD;
    *hostTime = anchor + (UInt64)(stamps * ticksPerPeriod);
    *seed = 1;
    pthread_mutex_unlock(&lock);
    return 0;
}

static OSStatus WillDoIOOperation(AudioServerPlugInDriverRef d, AudioObjectID device, UInt32 client, UInt32 op,
                                  Boolean *will, Boolean *inPlace) {
    *will = op == kAudioServerPlugInIOOperationReadInput;
    *inPlace = true;
    return 0;
}

static OSStatus BeginEndIO(AudioServerPlugInDriverRef d, AudioObjectID device, UInt32 client, UInt32 op, UInt32 frames,
                           const AudioServerPlugInIOCycleInfo *cycle) {
    return 0;
}

static OSStatus DoIOOperation(AudioServerPlugInDriverRef d, AudioObjectID device, AudioObjectID stream, UInt32 client,
                              UInt32 op, UInt32 frames, const AudioServerPlugInIOCycleInfo *cycle, void *main, void *second) {
    Float32 *out = main;
    // WHY: a real microphone never sends exact zeros; some apps treat digital silence as a blocked microphone.
    for (UInt32 i = 0; i < frames && out; i++) out[i] = ((Float32)((noise = noise * 1664525 + 1013904223) >> 16) / 65536.0f - 0.5f) * 0.002f;
    return 0;
}

static OSStatus Initialize(AudioServerPlugInDriverRef d, AudioServerPlugInHostRef h) {
    host = h;
    setRate(IDLE_RATE);
    return 0;
}

static OSStatus CreateDevice(AudioServerPlugInDriverRef d, CFDictionaryRef desc, const AudioServerPlugInClientInfo *c, AudioObjectID *out) {
    return kAudioHardwareUnsupportedOperationError;
}

static OSStatus DestroyDevice(AudioServerPlugInDriverRef d, AudioObjectID o) { return kAudioHardwareUnsupportedOperationError; }
static OSStatus Client(AudioServerPlugInDriverRef d, AudioObjectID o, const AudioServerPlugInClientInfo *c) { return 0; }
static ULONG Ref(void *d) { return 1; }
static HRESULT QueryInterface(void *d, REFIID uuid, LPVOID *out);

static AudioServerPlugInDriverInterface interface = {
    NULL, QueryInterface, Ref, Ref, Initialize, CreateDevice, DestroyDevice, Client, Client,
    PerformDeviceConfigurationChange, AbortDeviceConfigurationChange, HasProperty, IsPropertySettable,
    GetPropertyDataSize, GetPropertyData, SetPropertyData, StartIO, StopIO, GetZeroTimeStamp, WillDoIOOperation,
    BeginEndIO, DoIOOperation, BeginEndIO};
static AudioServerPlugInDriverInterface *interfacePtr = &interface;
static AudioServerPlugInDriverRef driver = &interfacePtr;

static HRESULT QueryInterface(void *d, REFIID uuid, LPVOID *out) {
    CFUUIDRef asked = CFUUIDCreateFromUUIDBytes(NULL, uuid);
    Boolean ok = CFEqual(asked, IUnknownUUID) || CFEqual(asked, kAudioServerPlugInDriverInterfaceUUID);
    CFRelease(asked);
    *out = ok ? driver : NULL;
    return ok ? S_OK : E_NOINTERFACE;
}

void *ProofreelHeadsetCreate(CFAllocatorRef allocator, CFUUIDRef type) {
    return CFEqual(type, kAudioServerPlugInTypeUUID) ? driver : NULL;
}
