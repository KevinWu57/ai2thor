using System;
using System.IO;
using System.Linq;
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using Unity.Barracuda;

public class ChangeFiles : MonoBehaviour
{
    public UnityEngine.Object[] changeFiles;
    public bool makeChanges;
    private GestureRecording gestureRecording1;
    private GestureRecording gestureRecording2;

    void Update()
    {
        if (makeChanges)
        {
            int length = changeFiles.Length;
            for(int i = length-1; i>0; i--)
            {
                // Load the summary file
                string summary_path1 = Directory.GetCurrentDirectory() + $"/Assets/GestureMocap/Recordings/test/summaries/" + changeFiles[i-1].name + ".json";
                StreamReader sr_summary1 = new StreamReader(summary_path1);
                string summary_json1 = sr_summary1.ReadToEnd();
                gestureRecording1 = JsonUtility.FromJson<GestureRecording>(summary_json1);

                // Load the summary file
                string summary_path2 = Directory.GetCurrentDirectory() + $"/Assets/GestureMocap/Recordings/test/summaries/" + changeFiles[i].name + ".json";
                StreamReader sr_summary2 = new StreamReader(summary_path2);
                string summary_json2 = sr_summary2.ReadToEnd();
                gestureRecording2 = JsonUtility.FromJson<GestureRecording>(summary_json2);

                gestureRecording2.targetID = gestureRecording1.targetID;
                gestureRecording2.targetType = gestureRecording1.targetType;
                gestureRecording2.targetSimObjType = gestureRecording1.targetSimObjType;
                gestureRecording2.targetPos = gestureRecording1.targetPos;
                gestureRecording2.instruction = gestureRecording1.instruction;

                gestureRecording2.targetToHuman = gestureRecording2.targetPos - gestureRecording2.humanPos;

                if (File.Exists(summary_path2))
                {
                    File.Delete(summary_path2);
                }
                File.WriteAllText(summary_path2, JsonUtility.ToJson(gestureRecording2));
            }

            makeChanges = false;
        }
    }
}