import React from "react";
import {Composition} from "remotion";
import {Diary, selectTrades, OPEN, CLOSE, type Props} from "./Diary";
import {sceneFrames} from "./TradeScene";
import {Onboarding, onboardingFrames, FPS} from "./Onboarding";

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Diary"
      component={Diary}
      fps={30}
      width={1920}
      height={1080}
      durationInFrames={600}
      defaultProps={{mode: "all", title: "Traders Diary", subtitle: ""} as Props}
      calculateMetadata={({props}) => ({
        // The length depends on which trades the cut contains, so it is worked
        // out from the props rather than fixed on the composition.
        durationInFrames:
          OPEN + selectTrades(props).reduce((a, t) => a + sceneFrames(t), 0) + CLOSE,
      })}
    />
    <Composition
      id="Onboarding"
      component={Onboarding}
      fps={FPS}
      width={1920}
      height={1080}
      durationInFrames={onboardingFrames()}
    />
  </>
);
