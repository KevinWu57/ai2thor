using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Windows.Speech;

public class MocapController : MonoBehaviour
{
    [Tooltip("The maximum frame the animation is recorded.")]
	public int maxFrameCount = 100;
	[Tooltip("The position this recording is referring to.")]
	public Vector3 positionReferredTo = Vector3.zero;
    private KinectFbxRecorder motionRecorder;
    public GameObject targetIndicator;
    public GameObject currentIndicator;

    [Header("Voice Recognition")]
    public ConfidenceLevel confidence = ConfidenceLevel.Low;
    public Text infoText;
    protected DictationRecognizer dictationRecognizer;

    // private bool isUserSpeaking = false;
    private bool isRecording = false;

    private string filename = "";
    private GestureRecording gestureRecording;
    private AudioRecorder audioRecorder;
    private Camera recordingCam;

    private Transform human;
    public Transform target;
    public SimObjType targetObjType;

    private string sceneName;

    private List<GameObject> spawnedObjects;

    private void Start() 
    {
        audioRecorder = FindObjectOfType<AudioRecorder>();
        recordingCam = GameObject.Find("Neck").GetComponent<Camera>();

        human = GameObject.Find("HumanMocapAnimator").transform;

        sceneName = UnityEngine.SceneManagement.SceneManager.GetActiveScene().name.Split('_')[0];

        spawnedObjects = FindObjectOfType<PhysicsSceneManager>().SpawnedObjects;

        // Initialize the motion recorder
        motionRecorder = FindObjectOfType<KinectFbxRecorder>();
        motionRecorder.maxFrameCount = maxFrameCount;
        motionRecorder.positionReferredTo = positionReferredTo;

        // Initialize dictation recognizer
        StartDictationEngine();

        if(!SelectTarget()) return;
        infoText.text = $"Please speak an instruction with {targetObjType.ToString()}: ";
    }

    /// <summary>
    /// Hypotethis are thrown super fast, but could have mistakes.
    /// </summary>
    /// <param name="text"></param>
    private void DictationRecognizer_OnDictationHypothesis(string text)
    {
        if (isRecording)
        {
            infoText.text = text;
        }
    }

    /// <summary>
    /// thrown when engine has some messages, that are not specifically errors
    /// </summary>
    /// <param name="completionCause"></param>
    private void DictationRecognizer_OnDictationComplete(DictationCompletionCause completionCause)
    {
        if (completionCause != DictationCompletionCause.Complete)
        {
            Debug.LogWarningFormat("Dictation completed unsuccessfully: {0}.", completionCause);


            switch (completionCause)
            {
                case DictationCompletionCause.TimeoutExceeded:
                case DictationCompletionCause.PauseLimitExceeded:
                    //we need a restart
                    CloseDictationEngine();
                    StartDictationEngine();
                    break;

                case DictationCompletionCause.UnknownError:
                case DictationCompletionCause.AudioQualityFailure:
                case DictationCompletionCause.MicrophoneUnavailable:
                case DictationCompletionCause.NetworkFailure:
                    //error without a way to recover
                    CloseDictationEngine();
                    break;

                case DictationCompletionCause.Canceled:
                    //happens when focus moved to another application 

                case DictationCompletionCause.Complete:
                    CloseDictationEngine();
                    StartDictationEngine();
                    break;
            }
        }
    }

    /// <summary>
    /// Resulted complete phrase will be determined once the person stops speaking. the best guess from the PC will go on the result.
    /// </summary>
    /// <param name="text"></param>
    /// <param name="confidence"></param>
    private void DictationRecognizer_OnDictationResult(string text, ConfidenceLevel confidence)
    {
        if (!isRecording)
        {
            if(text == "start")
            {
                infoText.text = "Complete sentence is: ";

                isRecording = true;

                filename = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss")+"_mocap";
                gestureRecording = new GestureRecording();

                audioRecorder.StartRecording();
            }
        }
        else
        {
            // Check if the recorded instruction contains the target
            if (!CheckInsturctionWithTarget(text))
            {
                infoText.text = $"Your instruction does not contain the {targetObjType.ToString()}. Please start again.";
                audioRecorder.RestartRecording();
                return;
            }

            infoText.text = $"Complete sentence is: <b>{text}</b>";
            gestureRecording.instruction = text;

            if (isRecording)
            {
                isRecording = false;

                CamCapture(recordingCam, filename, ref gestureRecording);
                motionRecorder.StartRecording(filename, ref gestureRecording);
                audioRecorder.Save(ref gestureRecording, filename);
                LogEnvironmentInfo(ref gestureRecording);
                SaveRecording(filename, gestureRecording);

                if (!SelectTarget()) {infoText.text="Target not selected"; return;}
                infoText.text = $"Please speak an instruction with {targetObjType.ToString()}: ";
            }
        }
    }

    private bool SelectTarget()
    {
        // Destroy current dicator first
        if (currentIndicator) Destroy(currentIndicator);
        int t = 0;
        bool targetFound = false;
        while(t<100)
        {
            target = spawnedObjects[UnityEngine.Random.Range(0, spawnedObjects.Count)].transform;
            targetObjType = target.GetComponent<SimObjPhysics>().ObjType;
            // Check if the target object type is possible and not contained in a receptable
            if(Enum.IsDefined(typeof(TargetObjType), targetObjType.ToString()) && target.parent.name=="Objects") {targetFound = true; break;}
        }
        if(!targetFound) 
        {
            infoText.text = "Cannot find a target object!";
            return false;
        }
        // Instantiate a target indicator for recording
        currentIndicator = Instantiate(targetIndicator, target.position, Quaternion.identity);
        return true;
    }

    private bool CheckInsturctionWithTarget(string text)
    {
        text = text.ToLower();
        return text.Contains(targetObjType.ToString().ToLower());
    }

    private void LogEnvironmentInfo(ref GestureRecording recording)
    {
        // Log room type and number
        int sceneNum = int.Parse(sceneName.Substring(9));
        recording.sceneNum = sceneNum;
        if (sceneNum <= 30) recording.sceneType = "Kitchen";
        else if (sceneNum <= 300) recording.sceneType = "LivingRoom";
        else if (sceneNum <= 400) recording.sceneType = "Bedroom";
        else if (sceneNum <= 500) recording.sceneType = "Bathroom";

        // Log human position and orientation
        recording.humanPos = human.position/10f;
        recording.humanRot = human.rotation.eulerAngles.y/360f;

        // Log target information
        recording.targetPos = target.position/10f;
        recording.targetType = target.GetComponent<SimObjPhysics>().ObjType.ToString();
        recording.targetToHuman = recording.targetPos - recording.humanPos;
    }

    private void SelectTargetFromInstruction(string sentence)
    {
        // Assume the last word of the sentence is the target
        string targetStr = sentence.Split(' ').Last();
    }

    private void DictationRecognizer_OnDictationError(string error, int hresult)
    {
        Debug.LogErrorFormat("Dictation error: {0}; HResult = {1}.", error, hresult);
    }


    private void OnApplicationQuit()
    {
        CloseDictationEngine();
    }

    private void StartDictationEngine()
    {
        isRecording = false;

        dictationRecognizer = new DictationRecognizer(confidence);

        dictationRecognizer.DictationHypothesis += DictationRecognizer_OnDictationHypothesis;
        dictationRecognizer.DictationResult += DictationRecognizer_OnDictationResult;
        dictationRecognizer.DictationComplete += DictationRecognizer_OnDictationComplete;
        dictationRecognizer.DictationError += DictationRecognizer_OnDictationError;

        dictationRecognizer.Start();
    }

    private void CloseDictationEngine()
    {
        if (dictationRecognizer != null)
        {
            dictationRecognizer.DictationHypothesis -= DictationRecognizer_OnDictationHypothesis;
            dictationRecognizer.DictationComplete -= DictationRecognizer_OnDictationComplete;
            dictationRecognizer.DictationResult -= DictationRecognizer_OnDictationResult;
            dictationRecognizer.DictationError -= DictationRecognizer_OnDictationError;

            if (dictationRecognizer.Status == SpeechSystemStatus.Running)
                dictationRecognizer.Stop();
            
            dictationRecognizer.Dispose();
        }
    }

    // Capture camera image
    public void CamCapture(Camera Cam, string filename, ref GestureRecording recording)
    {
        RenderTexture currentRT = RenderTexture.active;
        RenderTexture rt = new RenderTexture(224, 224, 24);
        Cam.targetTexture = rt;
        RenderTexture.active = Cam.targetTexture;
 
        Cam.Render();
 
        Texture2D Image = new Texture2D(Cam.targetTexture.width, Cam.targetTexture.height);
        Image.ReadPixels(new Rect(0, 0, Cam.targetTexture.width, Cam.targetTexture.height), 0, 0);
        Image.Apply();
        RenderTexture.active = currentRT;
        Cam.targetTexture = null;
 
        var Bytes = Image.EncodeToPNG();
        Destroy(Image);
 
        File.WriteAllBytes(Application.dataPath + "/GestureMocap/Recordings/images/" + filename + ".png", Bytes);
        recording.image += filename + ".png";
    }

    // Save GestureRecording object as a JSON file format
    public void SaveRecording(string fileName, GestureRecording recording)
    {
        string path = Application.dataPath + "/GestureMocap/Recordings/" + filename + ".json";
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        File.WriteAllText(path, JsonUtility.ToJson(recording));
    }
}

/// <summary>
/// Object type that can be selected as the target
/// </summary>
public enum TargetObjType: int
{
    Apple = 0,
	Tomato = 1,
	Bread = 2,
	Knife = 4,
	Fork = 5,
	Spoon = 6,
	Potato = 7,
	Plate = 8,
	Cup = 9
}
